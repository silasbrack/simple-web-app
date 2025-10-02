-- name: get_news(limit, offset, max_published_time)
SELECT id, title, text, published
FROM news_item
WHERE language = 'english'
  AND (published < :max_published_time)
ORDER BY published DESC, id ASC
LIMIT :limit
OFFSET :offset;

-- name: search_news(query, limit)
SELECT title, text
FROM news_item_fts(:query)
LIMIT :limit;

-- name: get_news_by_category(category_id, limit, offset, max_published_time)
SELECT ni.id, ni.title, ni.text, ni.published
FROM news_item AS ni
INNER JOIN news_item_category AS nic
  ON nic.news_item_id = ni.id
WHERE ni.language = 'english'
  AND (ni.published < :max_published_time)
  AND nic.category_id = :category_id
ORDER BY ni.published DESC, ni.id ASC
LIMIT :limit
OFFSET :offset;

-- name: get_categories_for_news(news_item_id)
SELECT c.id, c.name
FROM news_item_category AS nic
INNER JOIN category AS c
  ON c.id = nic.category_id
WHERE nic.news_item_id = :news_item_id;

-- name: get_categories(limit)
SELECT id, name
FROM category
ORDER BY id
LIMIT :limit;

