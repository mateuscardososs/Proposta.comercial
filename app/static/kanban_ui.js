function normalize(value) {
  return String(value ?? "").trim().toLocaleLowerCase("pt-BR");
}


export async function postMove({ id, payload, endpointTemplate, fetchImpl = fetch }) {
  const response = await fetchImpl(endpointTemplate.replace("{id}", String(id)), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("Não foi possível mover o item. Tente novamente.");
  }
  return response;
}


export function taskMatchesFilters(task, filters = {}) {
  const search = normalize(filters.search);
  if (search && !normalize(task.search).includes(search)) return false;
  for (const key of ["status", "owner", "client"]) {
    const expected = normalize(filters[key]);
    if (expected && normalize(task[key]) !== expected) return false;
  }

  const deadlineFilter = normalize(filters.deadline);
  if (!deadlineFilter) return true;
  const deadline = String(task.deadline ?? "");
  const today = String(filters.today ?? "");
  if (deadlineFilter === "none") return deadline === "";
  if (deadlineFilter === "today") return Boolean(deadline && today && deadline === today);
  if (deadlineFilter === "overdue") return Boolean(deadline && today && deadline < today);
  return true;
}


export function filterCards(cards, filters = {}) {
  let visible = 0;
  for (const card of Array.from(cards)) {
    const matches = taskMatchesFilters(card.dataset ?? {}, filters);
    card.hidden = !matches;
    if (matches) visible += 1;
  }
  return visible;
}


function getDragAfterElement(container, y) {
  const elements = [...container.querySelectorAll(".kanban-card:not(.dragging):not([hidden])")];
  return elements.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    return offset < 0 && offset > closest.offset
      ? { offset, element: child }
      : closest;
  }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
}


function insertAtOrigin(card, zone, nextSibling) {
  if (nextSibling && nextSibling.parentNode === zone) zone.insertBefore(card, nextSibling);
  else zone.appendChild(card);
}


export function bootstrapKanban(board) {
  if (!board) return null;
  const cards = [...board.querySelectorAll(".kanban-card")];
  const dropzones = [...board.querySelectorAll("[data-dropzone]")];
  const scope = board.closest("[data-kanban-scope]") || board.parentElement;
  const errorRegion = scope?.querySelector?.("[data-kanban-error]") || null;
  const filterRoot = scope?.querySelector?.("[data-board-filters]") || null;
  let draggedCard = null;
  let originZone = null;
  let originNextSibling = null;

  const showError = (message) => {
    if (!errorRegion) return;
    errorRegion.textContent = message;
    errorRegion.classList.add("visible");
  };
  const clearError = () => errorRegion?.classList.remove("visible");
  const updateCounters = () => {
    board.querySelectorAll(".kanban-column").forEach((column) => {
      const visibleCards = column.querySelectorAll(".kanban-card:not([hidden])");
      const badge = column.querySelector(".kanban-column-title .badge");
      if (badge) badge.textContent = visibleCards.length;
      const empty = column.querySelector("[data-column-empty]");
      if (empty) empty.hidden = visibleCards.length > 0;
    });
  };
  const payloadFor = (card, zone) => {
    const payload = { status: zone.closest(".kanban-column").dataset.status };
    if (board.dataset.ordered === "true") {
      payload.ordem = [...zone.querySelectorAll(".kanban-card")].indexOf(card);
    }
    return payload;
  };
  const persist = async (card, previousZone, previousNextSibling) => {
    try {
      await postMove({
        id: card.dataset.id,
        payload: payloadFor(card, card.parentElement),
        endpointTemplate: board.dataset.endpointTemplate,
      });
      card.dataset.status = card.closest(".kanban-column").dataset.status;
      updateCounters();
      clearError();
      return true;
    } catch (error) {
      insertAtOrigin(card, previousZone, previousNextSibling);
      updateCounters();
      showError(error.message);
      return false;
    }
  };

  cards.forEach((card) => {
    card.addEventListener("dragstart", (event) => {
      draggedCard = card;
      originZone = card.parentElement;
      originNextSibling = card.nextElementSibling;
      card.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.id);
      clearError();
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      dropzones.forEach((zone) => zone.classList.remove("drag-over"));
    });
  });

  dropzones.forEach((zone) => {
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", async (event) => {
      event.preventDefault();
      zone.classList.remove("drag-over");
      if (!draggedCard || !originZone) return;
      const card = draggedCard;
      const previousZone = originZone;
      const previousNextSibling = originNextSibling;
      if (board.dataset.ordered !== "true" && zone === previousZone) {
        insertAtOrigin(card, previousZone, previousNextSibling);
      } else {
        const afterElement = getDragAfterElement(zone, event.clientY);
        if (afterElement) zone.insertBefore(card, afterElement);
        else zone.appendChild(card);
        await persist(card, previousZone, previousNextSibling);
      }
      draggedCard = null;
      originZone = null;
      originNextSibling = null;
    });
  });

  board.addEventListener("change", async (event) => {
    const control = event.target.closest("[data-task-move]");
    if (!control) return;
    const card = control.closest(".kanban-card");
    const previousStatus = card.dataset.status;
    const previousZone = card.parentElement;
    const previousNextSibling = card.nextElementSibling;
    const destination = board.querySelector(`.kanban-column[data-status="${control.value}"] [data-dropzone]`);
    if (!destination || destination === previousZone) return;
    destination.appendChild(card);
    const moved = await persist(card, previousZone, previousNextSibling);
    if (!moved) control.value = previousStatus;
  });

  if (filterRoot) {
    const applyFilters = () => {
      const filters = {
        search: filterRoot.querySelector("[data-filter-search]")?.value,
        status: filterRoot.querySelector("[data-filter-status]")?.value,
        owner: filterRoot.querySelector("[data-filter-owner]")?.value,
        client: filterRoot.querySelector("[data-filter-client]")?.value,
        deadline: filterRoot.querySelector("[data-filter-deadline]")?.value,
        today: board.dataset.today,
      };
      filterCards(cards, filters);
      updateCounters();
      const feedback = filterRoot.querySelector("[data-filter-feedback]");
      if (feedback) feedback.textContent = `${cards.filter((card) => !card.hidden).length} tarefa(s) visível(is)`;
    };
    filterRoot.addEventListener("input", applyFilters);
    filterRoot.addEventListener("change", applyFilters);
  }

  updateCounters();
  return { updateCounters };
}
