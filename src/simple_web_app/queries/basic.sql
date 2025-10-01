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

-- name: get_categories_for_news(id)
SELECT category_id
FROM news_item_category
WHERE id = :id;

-- name: get_categories(limit)
SELECT category_id
FROM news_item_category
GROUP BY category_id
ORDER BY COUNT(*) DESC
LIMIT :limit;

