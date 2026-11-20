ALTER TABLE questions ADD COLUMN student_id VARCHAR(36) REFERENCES users(id);

ALTER TABLE questions ADD COLUMN source_version_id VARCHAR(36) REFERENCES material_versions(id);

ALTER TABLE questions ADD COLUMN purpose VARCHAR(20) NOT NULL DEFAULT 'bank';

CREATE INDEX ix_questions_student_id ON questions(student_id);

CREATE INDEX ix_questions_source_version_id ON questions(source_version_id);

CREATE TABLE daily_plans (
	student_id VARCHAR(36) NOT NULL, 
	section_id VARCHAR(36) NOT NULL, 
	day DATE NOT NULL, 
	week INTEGER NOT NULL, 
	day_index INTEGER NOT NULL, 
	job_id VARCHAR(36) NOT NULL, 
	context JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(student_id) REFERENCES users (id), 
	FOREIGN KEY(section_id) REFERENCES sections (id), 
	FOREIGN KEY(job_id) REFERENCES jobs (id)
);

CREATE INDEX ix_daily_plans_section_id ON daily_plans (section_id);

CREATE INDEX ix_daily_plans_student_id ON daily_plans (student_id);

CREATE UNIQUE INDEX uq_plan_student_section_day ON daily_plans (student_id, section_id, day);

ALTER TABLE daily_plans ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON daily_plans FROM PUBLIC;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON daily_plans FROM anon; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON daily_plans FROM authenticated; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON daily_plans TO service_role; END IF; END $$;

CREATE TABLE concept_videos (
	course_id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36) NOT NULL, 
	concept_id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	script_job_id VARCHAR(36), 
	script JSON, 
	request JSON, 
	provider_session_id VARCHAR(150), 
	provider_video_id VARCHAR(150), 
	object_key VARCHAR(300), 
	duration_seconds FLOAT, 
	error_code VARCHAR(80), 
	next_poll_at TIMESTAMP WITH TIME ZONE, 
	lease_token VARCHAR(36), 
	lease_until TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id), 
	FOREIGN KEY(version_id) REFERENCES material_versions (id), 
	FOREIGN KEY(concept_id) REFERENCES concepts (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(script_job_id) REFERENCES jobs (id)
);

CREATE INDEX ix_concept_videos_concept_id ON concept_videos (concept_id);

CREATE INDEX ix_concept_videos_course_id ON concept_videos (course_id);

CREATE INDEX ix_concept_videos_status ON concept_videos (status);

CREATE INDEX ix_concept_videos_version_id ON concept_videos (version_id);

CREATE UNIQUE INDEX uq_video_source_concept ON concept_videos (version_id, concept_id);

ALTER TABLE concept_videos ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON concept_videos FROM PUBLIC;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON concept_videos FROM anon; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON concept_videos FROM authenticated; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON concept_videos TO service_role; END IF; END $$;

CREATE TABLE practice_exercises (
	course_id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36) NOT NULL, 
	concept_id VARCHAR(36), 
	source_key VARCHAR(64) NOT NULL, 
	position INTEGER NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	language VARCHAR(10) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	prompt TEXT NOT NULL, 
	template TEXT NOT NULL, 
	reference TEXT NOT NULL, 
	blanks JSON NOT NULL, 
	tests JSON NOT NULL, 
	sources JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id), 
	FOREIGN KEY(version_id) REFERENCES material_versions (id), 
	FOREIGN KEY(concept_id) REFERENCES concepts (id)
);

CREATE INDEX ix_practice_exercises_concept_id ON practice_exercises (concept_id);

CREATE INDEX ix_practice_exercises_course_id ON practice_exercises (course_id);

CREATE INDEX ix_practice_exercises_version_id ON practice_exercises (version_id);

CREATE UNIQUE INDEX uq_exercise_source_key ON practice_exercises (version_id, source_key, kind);

ALTER TABLE practice_exercises ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON practice_exercises FROM PUBLIC;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON practice_exercises FROM anon; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON practice_exercises FROM authenticated; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON practice_exercises TO service_role; END IF; END $$;

CREATE TABLE practice_sessions (
	student_id VARCHAR(36) NOT NULL, 
	section_id VARCHAR(36) NOT NULL, 
	day DATE NOT NULL, 
	week INTEGER NOT NULL, 
	exercise_ids JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(student_id) REFERENCES users (id), 
	FOREIGN KEY(section_id) REFERENCES sections (id)
);

CREATE INDEX ix_practice_sessions_section_id ON practice_sessions (section_id);

CREATE INDEX ix_practice_sessions_student_id ON practice_sessions (student_id);

CREATE UNIQUE INDEX uq_practice_student_section_day ON practice_sessions (student_id, section_id, day);

ALTER TABLE practice_sessions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON practice_sessions FROM PUBLIC;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON practice_sessions FROM anon; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON practice_sessions FROM authenticated; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON practice_sessions TO service_role; END IF; END $$;

CREATE TABLE practice_attempts (
	student_id VARCHAR(36) NOT NULL, 
	section_id VARCHAR(36) NOT NULL, 
	exercise_id VARCHAR(36) NOT NULL, 
	practice_session_id VARCHAR(36) NOT NULL, 
	source TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	correct BOOLEAN, 
	independent BOOLEAN NOT NULL, 
	feedback JSON, 
	job_id VARCHAR(36), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(student_id) REFERENCES users (id), 
	FOREIGN KEY(section_id) REFERENCES sections (id), 
	FOREIGN KEY(exercise_id) REFERENCES practice_exercises (id), 
	FOREIGN KEY(practice_session_id) REFERENCES practice_sessions (id), 
	FOREIGN KEY(job_id) REFERENCES jobs (id)
);

CREATE INDEX ix_practice_attempts_exercise_id ON practice_attempts (exercise_id);

CREATE INDEX ix_practice_attempts_practice_session_id ON practice_attempts (practice_session_id);

CREATE INDEX ix_practice_attempts_section_id ON practice_attempts (section_id);

CREATE INDEX ix_practice_attempts_student_id ON practice_attempts (student_id);

ALTER TABLE practice_attempts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON practice_attempts FROM PUBLIC;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON practice_attempts FROM anon; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON practice_attempts FROM authenticated; END IF; END $$;

DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON practice_attempts TO service_role; END IF; END $$;
