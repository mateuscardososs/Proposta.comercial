# SDD Task 6 report — administrative steps, corrections, reminders

Implemented the assistant adapter paths for administrative workflow transitions, append-only corrections, and service-linked reminders. Each mutation remains behind its own confirmation action. A correction to an unconfirmed service draft cancels the old action and creates a replacement confirmation with a new token; a correction to a persisted event appends a correction row and calls the domain projection rebuild. Confirming reminders uses `board_service.create_task` and `ServiceTaskLink`; replay returns the same task links.

Added projection grounding for service query replies: explicit technical/administrative status claims tied to a call ID must match the tool result; effective inspection events cannot be denied or invented. The compact prompt payload now includes bounded recent event facts and all five step statuses. A successful read result permits natural response generation after the read tool is removed from the next-round allowlist; no repeated service read tool is exposed. Reminder confirmation shows an absolute localized date when a relative due date was supplied. Added UI links for the service call and all linked tasks.

TDD regression additions cover `unknown -> pending -> waiting_customer`, persisted correction preserving source event and rebuilding current state, stale draft confirmation rejected after correction, reminder date resolution and duplicate confirmation, plus links rendered for service and task URLs.

Validation: focused Python tests => **85 passed, 1 skipped** (live Ollama test intentionally opt-in in the focused suite). Full Python suite => **409 passed, 5 skipped**. All JavaScript chat/voice tests => **18 passed**. Real HTTP consultation through Ollama in the 8011 synthetic instance returned the expected inspection event and pending report; the real Ollama opt-in creation test passed.

No commit, push, deploy, operational DB mutation, Yahoo mailbox access, or change to port 8000.
