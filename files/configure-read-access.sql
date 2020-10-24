-- Taken from: https://gist.github.com/oinopion/4a207726edba8b99fd0be31cb28124d0

-- Create a group
CREATE ROLE readaccess;

-- Grant access to existing tables
GRANT USAGE ON SCHEMA public TO readaccess;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readaccess;

-- Grant access to future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readaccess;

-- Create a readonly user with password
CREATE USER readonly WITH PASSWORD 'pass';
GRANT readaccess TO readonly;