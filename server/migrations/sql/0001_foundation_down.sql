-- Destructive downgrade, intended only for disposable development/test databases.
-- Never use to roll back a customer deployment containing accepted uploads.
DROP SCHEMA platform CASCADE;
