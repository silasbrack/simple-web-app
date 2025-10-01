CREATE TABLE news_item (
  id INTEGER PRIMARY KEY,
  url TEXT,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  published TEXT NOT NULL,
  author TEXT,
  language TEXT NOT NULL
) STRICT;

CREATE TABLE category (
  id INTEGER PRIMARY KEY,
  name TEXT
) STRICT;

CREATE TABLE news_item_category (
  id INTEGER PRIMARY KEY,
  news_item_id INTEGER NOT NULL,
  category_id INTEGER NOT NULL,
  FOREIGN KEY(news_item_id) REFERENCES news_item(id),
  FOREIGN KEY(category_id) REFERENCES category(id)
) STRICT;

CREATE VIRTUAL TABLE news_item_fts USING fts5(
  title,
  text,
  content='news_item',
  content_rowid='id'
);

CREATE TRIGGER news_item_ai AFTER INSERT ON news_item BEGIN
    INSERT INTO news_item_fts(rowid, title, text)
    VALUES (new.id, new.title, new.text);
END;
CREATE TRIGGER news_item_au AFTER UPDATE ON news_item BEGIN
    UPDATE news_item_fts SET title=new.title, text=new.text
    WHERE rowid=old.id;
END;
CREATE TRIGGER news_item_ad AFTER DELETE ON news_item BEGIN
    DELETE FROM news_item_fts WHERE rowid=old.id;
END;


