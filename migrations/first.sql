CREATE TABLE todos (
  id INTEGER PRIMARY KEY,
  content TEXT,
  create_timestamp TEXT,
  done INT DEFAULT 0
) STRICT;
