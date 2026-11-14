CREATE INDEX idx_photo_tags_tag_id ON photo_tags (tag_id);
CREATE INDEX idx_photos_location ON photos (location_country, location_city);
CREATE INDEX idx_photos_size ON photos (file_size DESC);
CREATE INDEX ix_faces_file_hash ON faces (file_hash);
CREATE INDEX ix_faces_person_id ON faces (person_id);
CREATE INDEX ix_photos_date_taken ON photos (date_taken);
CREATE TABLE captions (
	file_hash VARCHAR(64) NOT NULL, 
	caption TEXT, 
	model VARCHAR(100), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (file_hash), 
	FOREIGN KEY(file_hash) REFERENCES photos (file_hash)
);
CREATE TABLE config_store (
	"key" VARCHAR(255) NOT NULL, 
	value TEXT NOT NULL, 
	PRIMARY KEY ("key")
);
CREATE TABLE duplicate_groups (
	group_id INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (group_id)
);
CREATE TABLE duplicate_members (
	group_id INTEGER NOT NULL, 
	file_hash VARCHAR(64) NOT NULL, 
	PRIMARY KEY (group_id, file_hash), 
	FOREIGN KEY(group_id) REFERENCES duplicate_groups (group_id), 
	FOREIGN KEY(file_hash) REFERENCES photos (file_hash)
);
CREATE TABLE event_photos (
	event_id INTEGER NOT NULL, 
	file_hash VARCHAR(64) NOT NULL, 
	PRIMARY KEY (event_id, file_hash), 
	FOREIGN KEY(event_id) REFERENCES events (event_id), 
	FOREIGN KEY(file_hash) REFERENCES photos (file_hash)
);
CREATE TABLE events (
	event_id INTEGER NOT NULL, 
	name VARCHAR(300), 
	start_date DATETIME, 
	end_date DATETIME, 
	location TEXT, 
	photo_count INTEGER NOT NULL, cover_file_hash TEXT, summary TEXT, 
	PRIMARY KEY (event_id)
);
CREATE TABLE faces (
	face_id INTEGER NOT NULL, 
	file_hash VARCHAR(64) NOT NULL, 
	bbox_x INTEGER, 
	bbox_y INTEGER, 
	bbox_w INTEGER, 
	bbox_h INTEGER, 
	encoding BLOB, 
	person_id INTEGER, 
	confidence FLOAT, 
	face_thumbnail TEXT, 
	PRIMARY KEY (face_id), 
	FOREIGN KEY(file_hash) REFERENCES photos (file_hash), 
	FOREIGN KEY(person_id) REFERENCES persons (person_id)
);
CREATE TABLE hidden_person_groups (
	group_key VARCHAR(255) NOT NULL, 
	PRIMARY KEY (group_key)
);
CREATE TABLE persons (
	person_id INTEGER NOT NULL, 
	name VARCHAR(200), 
	representative_face_id INTEGER, 
	photo_count INTEGER NOT NULL, ignored BOOLEAN DEFAULT 0, 
	PRIMARY KEY (person_id)
);
CREATE TABLE photo_hashes (
	file_hash VARCHAR(64) NOT NULL, 
	phash VARCHAR(16), 
	ahash VARCHAR(16), 
	dhash VARCHAR(16), 
	PRIMARY KEY (file_hash), 
	FOREIGN KEY(file_hash) REFERENCES photos (file_hash)
);
CREATE TABLE photo_paths (
	file_hash VARCHAR(64) NOT NULL, 
	file_path TEXT NOT NULL, 
	PRIMARY KEY (file_hash, file_path), 
	FOREIGN KEY(file_hash) REFERENCES photos (file_hash)
);
CREATE TABLE photo_tags (
	file_hash VARCHAR(64) NOT NULL, 
	tag_id INTEGER NOT NULL, 
	confidence FLOAT, 
	PRIMARY KEY (file_hash, tag_id), 
	FOREIGN KEY(file_hash) REFERENCES photos (file_hash), 
	FOREIGN KEY(tag_id) REFERENCES tags (tag_id)
);
CREATE TABLE photos (
	file_hash VARCHAR(64) NOT NULL, 
	file_path TEXT NOT NULL, 
	file_name TEXT NOT NULL, 
	file_size INTEGER NOT NULL, 
	file_modified DATETIME, 
	mime_type VARCHAR(50), 
	width INTEGER, 
	height INTEGER, 
	date_taken DATETIME, 
	date_source VARCHAR(20), 
	camera_make VARCHAR(100), 
	camera_model VARCHAR(100), 
	lens_model VARCHAR(100), 
	focal_length FLOAT, 
	aperture FLOAT, 
	shutter_speed VARCHAR(20), 
	iso INTEGER, 
	orientation INTEGER, 
	gps_latitude FLOAT, 
	gps_longitude FLOAT, 
	gps_altitude FLOAT, 
	location_country VARCHAR(100), 
	location_city VARCHAR(200), 
	location_address TEXT, 
	live_photo_video TEXT, 
	motion_photo BOOLEAN NOT NULL, 
	is_favorite BOOLEAN NOT NULL, 
	indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, marked_for_print BOOLEAN DEFAULT 0 NOT NULL, exported_at DATETIME, flagged_for_removal BOOLEAN DEFAULT 0 NOT NULL, is_video BOOLEAN DEFAULT 0 NOT NULL, duration REAL, 
	PRIMARY KEY (file_hash)
);
CREATE TABLE stage_failures (
	file_hash VARCHAR(64) NOT NULL, 
	stage VARCHAR(20) NOT NULL, 
	error TEXT, 
	failed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (file_hash, stage), 
	FOREIGN KEY(file_hash) REFERENCES photos (file_hash)
);
CREATE TABLE tags (
	tag_id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	category VARCHAR(50), 
	PRIMARY KEY (tag_id), 
	UNIQUE (name)
);
