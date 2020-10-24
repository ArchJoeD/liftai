-- This file should ONLY contain SQL code that creates things, not SQL code that deletes things.
-- Due to the installation fallback mechanism, we can't modify the database such that older versions of code won't work.


/*********** Accelerometer **************/
-- This is defined as a model


ALTER TABLE accelerometer_data ADD COLUMN IF NOT EXISTS x_data float;
ALTER TABLE accelerometer_data ADD COLUMN IF NOT EXISTS y_data float;
ALTER TABLE accelerometer_data ADD COLUMN IF NOT EXISTS z_data float;
CREATE INDEX IF NOT EXISTS accelerometer_data_timestamp_idx ON accelerometer_data USING btree (timestamp);


/*********** Altimeter **************/
CREATE SEQUENCE IF NOT EXISTS altimeter_data_id_seq;
ALTER SEQUENCE altimeter_data_id_seq OWNER TO usr;
CREATE TABLE IF NOT EXISTS altimeter_data
(
  id integer NOT NULL DEFAULT nextval('altimeter_data_id_seq'::regclass),
  "timestamp" timestamp without time zone NOT NULL,
  altitude_x16 integer,
  temperature DOUBLE PRECISION,
  average_alt DOUBLE PRECISION,
  CONSTRAINT altimeter_data_pkey PRIMARY KEY (id)
)
WITH (
  OIDS=FALSE
);
ALTER TABLE altimeter_data OWNER TO usr;

CREATE INDEX IF NOT EXISTS altimeter_data_timestamp_idx ON altimeter_data USING btree (timestamp);


/*********** Data Sender ************/
CREATE SEQUENCE IF NOT EXISTS data_to_send_id_seq;
CREATE TABLE IF NOT EXISTS data_to_send
(
  id integer NOT NULL DEFAULT nextval('data_to_send_id_seq'::regclass),
  "timestamp" timestamp without time zone NOT NULL,
  endpoint character varying,
  payload json,
  flag boolean,
  resend boolean DEFAULT FALSE,
  success boolean,
  CONSTRAINT data_to_send_pkey PRIMARY KEY (id)
)
WITH (
  OIDS=FALSE
);

ALTER TABLE data_to_send ADD COLUMN IF NOT EXISTS resend boolean DEFAULT FALSE;
ALTER TABLE data_to_send ADD COLUMN IF NOT EXISTS success boolean;

ALTER SEQUENCE data_to_send_id_seq OWNER TO usr;
ALTER TABLE data_to_send OWNER TO usr;

CREATE OR REPLACE FUNCTION notify_trigger() RETURNS trigger AS $$
DECLARE
BEGIN
  PERFORM pg_notify('watchers', TG_TABLE_NAME || ',id,' || NEW.id );
  RETURN new;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS watched_table_trigger ON data_to_send;
CREATE TRIGGER watched_table_trigger AFTER INSERT ON data_to_send
FOR EACH ROW EXECUTE PROCEDURE notify_trigger();

CREATE SEQUENCE IF NOT EXISTS bank_trips_id_seq;
ALTER SEQUENCE bank_trips_id_seq OWNER TO usr;

CREATE TABLE IF NOT EXISTS bank_trips
(
  id integer NOT NULL DEFAULT nextval('bank_trips_id_seq'::regclass),
  "timestamp" timestamp without time zone NOT NULL,
  bank_trips integer,
  bank_elevators integer,
  CONSTRAINT bank_trips_pkey PRIMARY KEY (id)
)
WITH (
  OIDS=FALSE
);
ALTER TABLE bank_trips OWNER TO usr;

CREATE INDEX IF NOT EXISTS bank_trips_timestamp_idx ON bank_trips USING btree (timestamp);


/*********** Elisha ************/
-- Events are inputs to Elisha
CREATE SEQUENCE IF NOT EXISTS events_id_seq;
CREATE TABLE IF NOT EXISTS Events
(
    id integer NOT NULL DEFAULT nextval('events_id_seq'::regclass),
    occurred_at timestamp without time zone,
    detected_at timestamp without time zone,
    source text,                -- Application which generated the event
    event_type text,            -- Major type, such as shutdown or vibration anomaly
    event_subtype text,         -- Minor type, such as bank based shutdown or low frequency Z-axis vibration
    confidence numeric(4,2),    -- Most events have some est confidence that it's a real issue. Max is 99.99%
    details jsonb,              -- This is intended for test and debug use
    chart_info jsonb            -- JSON formatted info for creating a chart, usually NULL
)
WITH (
  OIDS=FALSE
);
ALTER TABLE Events OWNER TO usr;
ALTER SEQUENCE events_id_seq OWNER TO usr;

-- Problems are outputs from Elisha
CREATE SEQUENCE IF NOT EXISTS problems_id_seq;
CREATE TABLE IF NOT EXISTS Problems
(
    id integer NOT NULL DEFAULT nextval('problems_id_seq'::regclass),
    created_at timestamp without time zone DEFAULT NOW(),
    updated_at timestamp without time zone DEFAULT NOW(),
    started_at timestamp without time zone,
    ended_at timestamp without time zone,
    problem_type text NOT NULL,
    problem_subtype text,
    customer_info text,
    confidence numeric(4,2), -- Confidence level, up to 99.99%
    events integer[],
    details jsonb,              -- This is intended for test and debug use
    chart_info jsonb        -- JSON formatted info for creating a chart, usually NULL
)
WITH (
  OIDS=FALSE
);
ALTER TABLE Problems OWNER TO usr;
ALTER SEQUENCE problems_id_seq OWNER TO usr;

ALTER TABLE Problems ADD COLUMN IF NOT EXISTS updated_at timestamp without time zone DEFAULT NOW();
ALTER TABLE Problems ADD COLUMN IF NOT EXISTS created_at timestamp without time zone DEFAULT NOW();

/*********** Escalator Stoppage ************/
CREATE TABLE IF NOT EXISTS escalator_vibration
(
  "timestamp" timestamp without time zone NOT NULL,
  position integer NOT NULL,   -- This is the avg of position field from accelerometer_data, very low frequency vibration
  xy_freq_1 integer NOT NULL,      -- Lowest FFT frequency
  xy_freq_2 integer NOT NULL,
  xy_freq_3 integer NOT NULL,
  xy_freq_4 integer NOT NULL,
  xy_freq_5 integer NOT NULL,      -- Highest FFT frequency
  z_freq_1 integer NOT NULL,       -- Lowest FFT frequency
  z_freq_2 integer NOT NULL,
  z_freq_3 integer NOT NULL,
  z_freq_4 integer NOT NULL,
  z_freq_5 integer NOT NULL,       -- Highest FFT frequency
  CONSTRAINT escalator_vibration_pkey PRIMARY KEY ("timestamp")
)
WITH (
  OIDS=FALSE
);
ALTER TABLE escalator_vibration OWNER TO usr;


/*********** ROA Watch ************/
CREATE TABLE IF NOT EXISTS roa_watch_requests
(
  request_time   timestamp without time zone NOT NULL,
  enabled        boolean,
  CONSTRAINT roa_watch_requests_pkey PRIMARY KEY (request_time)
)
WITH (
  OIDS=FALSE
);

ALTER TABLE roa_watch_requests OWNER TO usr;


/*********** Trips ************/
CREATE TABLE IF NOT EXISTS Trips
(
    id SERIAL,
    start_accel integer,
    end_accel integer,
    start_time timestamp without time zone,
    end_time timestamp without time zone,
    is_up boolean,
    elevation_change integer,
    ending_floor integer,
    audio jsonb,
    floor_map_id integer
)
WITH (
  OIDS=FALSE
);
ALTER TABLE Trips OWNER TO usr;

DO $$
BEGIN
IF NOT EXISTS (SELECT constraint_name FROM information_schema.table_constraints where table_name = 'trips' and constraint_type = 'PRIMARY KEY')
THEN
  ALTER TABLE Trips ADD PRIMARY KEY (id);
END IF;
END $$;

CREATE TABLE IF NOT EXISTS Accelerations
(
    id SERIAL,
    start_time timestamp without time zone,
    duration integer,
    magnitude integer,
    is_start_of_trip boolean,
    is_positive boolean,
    audio jsonb
)
WITH (
  OIDS=FALSE
);
ALTER TABLE Accelerations OWNER TO usr;

DO $$
BEGIN
IF NOT EXISTS (SELECT constraint_name FROM information_schema.table_constraints where table_name = 'accelerations' and constraint_type = 'PRIMARY KEY')
THEN
  ALTER TABLE Accelerations ADD PRIMARY KEY (id);
END IF;
END $$;

ALTER TABLE Trips ADD COLUMN IF NOT EXISTS vibration_schema integer DEFAULT -1;
ALTER TABLE Trips ADD COLUMN IF NOT EXISTS vibration jsonb;
ALTER TABLE Trips ADD COLUMN IF NOT EXISTS audio jsonb;

ALTER TABLE Accelerations ADD COLUMN IF NOT EXISTS vibration_schema integer DEFAULT -1;
ALTER TABLE Accelerations ADD COLUMN IF NOT EXISTS vibration jsonb;
ALTER TABLE Accelerations ADD COLUMN IF NOT EXISTS audio jsonb;

-- This is TRUE when the elevation app has made an attempt to fill in the elevation_change field.
-- Sometimes it's not possible to get the elevation and we need a mechanism to distinguish from not-done-yet.
ALTER TABLE Trips ADD COLUMN IF NOT EXISTS elevation_processed boolean;

ALTER TABLE Trips ALTER COLUMN ending_floor TYPE text;

ALTER TABLE Trips ADD COLUMN IF NOT EXISTS floor_map_id integer;

ALTER TABLE Trips ADD COLUMN IF NOT EXISTS speed float;

CREATE INDEX IF NOT EXISTS trips_start_time_idx ON Trips USING btree (start_time);
CREATE INDEX IF NOT EXISTS trips_end_time_idx ON Trips USING btree (end_time);


/*********** Floor Detector ************/
CREATE TABLE IF NOT EXISTS floor_maps
(
    id SERIAL,
    start_time timestamp without time zone,
    last_update timestamp without time zone,    -- timestamp of last event or trip processed
    last_elevation integer,
    floors jsonb
)
WITH (
  OIDS=FALSE
);
ALTER TABLE floor_maps OWNER TO usr;

ALTER TABLE Trips ADD COLUMN IF NOT EXISTS floor_estimated_error integer;

DO $$
BEGIN
IF NOT EXISTS (SELECT constraint_name FROM information_schema.table_constraints where table_name = 'floor_maps'
            and constraint_type = 'PRIMARY KEY')
THEN
  ALTER TABLE floor_maps ADD PRIMARY KEY (id);
END IF;
END $$;
ALTER TABLE Trips ADD CONSTRAINT fk_trips_floor_maps FOREIGN KEY (floor_map_id)
            REFERENCES floor_maps (id) ON DELETE RESTRICT;


/********** Migrate trips without a floor_map_id **********/
-- We don't go back before July 1, 2020 to limit the migration processing.
WITH pairs AS (
  SELECT t.id AS trip_id,
    (SELECT id FROM floor_maps m WHERE m.start_time < t.start_time ORDER BY m.start_time DESC LIMIT 1) AS fmap_id
  FROM trips t WHERE t.floor_map_id IS NULL AND ending_floor IS NOT NULL AND start_time > '2020-07-01 00:00:00'
)
UPDATE trips
SET floor_map_id = pairs.fmap_id
FROM pairs
WHERE id = pairs.trip_id;


/*********** Audio ************/
CREATE TABLE IF NOT EXISTS audio
(
    id SERIAL,
    "timestamp" timestamp without time zone NOT NULL,
    nsamples INTEGER,
    sum_of_squares REAL        -- 6 decimal digits of precision, 1E-37 to 1E+37 range is enough
)
WITH (
  OIDS=FALSE
);
ALTER TABLE audio OWNER TO usr;

DO $$
BEGIN
IF NOT EXISTS (SELECT constraint_name FROM information_schema.table_constraints where table_name = 'audio'
            and constraint_type = 'PRIMARY KEY')
THEN
  ALTER TABLE audio ADD PRIMARY KEY (id);
END IF;
END $$;

CREATE INDEX IF NOT EXISTS audio_timestamp_idx ON audio USING btree (timestamp);
