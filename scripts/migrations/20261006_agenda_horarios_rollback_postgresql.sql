-- Reversível somente antes de gravar dados da agenda ou durações em tarefas.
-- Execute com a aplicação parada e somente em PostgreSQL do schema correto.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM daily_schedule_snapshots)
       OR EXISTS (SELECT 1 FROM work_availability_windows)
       OR EXISTS (SELECT 1 FROM fixed_commitments)
       OR EXISTS (SELECT 1 FROM daily_schedule_preferences)
       OR EXISTS (SELECT 1 FROM tasks WHERE estimated_duration_minutes IS NOT NULL)
    THEN
        RAISE EXCEPTION 'Rollback bloqueado: há configurações, snapshots ou estimativas a preservar';
    END IF;
END;
$$;

DROP TABLE fixed_commitments;
DROP TABLE daily_schedule_snapshots;
DROP TABLE work_availability_windows;
DROP TABLE daily_schedule_preferences;
ALTER TABLE tasks DROP COLUMN IF EXISTS estimated_duration_minutes;
DROP FUNCTION IF EXISTS reject_daily_schedule_mutation();

COMMIT;
