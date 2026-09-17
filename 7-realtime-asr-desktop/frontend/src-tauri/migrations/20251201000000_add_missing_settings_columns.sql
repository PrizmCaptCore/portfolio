-- Add missing columns to settings table
ALTER TABLE settings ADD COLUMN openRouterApiKey TEXT;
ALTER TABLE settings ADD COLUMN customOpenAIConfig TEXT;
