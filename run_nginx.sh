# Workaround to produce ETag headers for soundtouch device compatibility
# See also: https://github.com/deborahgu/soundcork/issues/129
# You have to set the soundcork IP in nginx-Etag.conf
docker run --rm --name nginx-ETag -p 8001:8001 -v $(pwd)/nginx-ETag.conf:/etc/nginx/conf.d/default.conf:ro nginx
