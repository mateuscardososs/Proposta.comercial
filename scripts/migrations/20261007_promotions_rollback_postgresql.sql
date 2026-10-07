BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM promotion_recipients)
       OR EXISTS (SELECT 1 FROM promotion_campaign_events)
       OR EXISTS (SELECT 1 FROM campaign_contact_consent_events)
       OR EXISTS (SELECT 1 FROM promotion_campaigns)
       OR EXISTS (SELECT 1 FROM client_campaign_contacts) THEN
        RAISE EXCEPTION 'Rollback recusado: há registros de campanhas ou consentimento que precisam ser preservados.';
    END IF;
END $$;

DROP TABLE promotion_campaign_events;
DROP TABLE promotion_recipients;
DROP TABLE promotion_campaigns;
DROP TABLE campaign_contact_consent_events;
DROP TABLE client_campaign_contacts;

COMMIT;
