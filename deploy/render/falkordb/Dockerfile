# FalkorDB with its password taken from FALKORDB_PASSWORD, for a platform (Render) that sets
# environment variables but cannot compose one from another. Same image as docker-compose.
FROM falkordb/falkordb:6.0.1
COPY start.sh /usr/local/bin/mandate-falkordb
RUN chmod 755 /usr/local/bin/mandate-falkordb
ENTRYPOINT ["/usr/local/bin/mandate-falkordb"]
