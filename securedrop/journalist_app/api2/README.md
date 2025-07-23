# Journalist API v2

This package implements and documents the synchronization strategy for the v2
Journalist API.

| File                                  | Contents                             |
| ------------------------------------- | ------------------------------------ |
| `README.md`                           | Specification                        |
| `__init__.py`                         | Server implementation                |
| `../../tests/test_journalist_api2.py` | Test suite for server implementation |

A client-side implementation should be able to interact with the endpoints
implemented in `__init__.py` according to this specification.

## Overview

The request/response schemas referred to in these sequence diagrams are defined
as mypy types in `__init__.py`.

### Initial synchronization

```mermaid
sequenceDiagram
participant Client
participant Server

alt Global
    Client -->> Server: GET /api/v2/index
else Sharded by UUID prefix
    Client -->> Server: GET /api/v2/index/<prefix>
end

Server ->> Client: ETag: abcdef<br>Index
Note over Client: New sources → "full sources" for which we want all metadata.
Client -->> Server: POST /api/v2/sources<br>SourceDelta
Server ->> Client: SourceMetadata
```

### Incremental synchronization

```mermaid
sequenceDiagram
participant Client
participant Server

Note over Client: Global version abcdef
Note over Client: Shard <prefix> version uvwxyz

alt Global
    Client -->> Server: GET /api/v2/index<br>If-None-Match: abcdef
else Sharded by UUID prefix
    Client -->> Server: GET /api/v2/index/<prefix><br>If-None-Match: uvwxyz
end

alt Up to date
    Server ->> Client: HTTP 304
else Out of date
    Server ->> Client: ETag: abcdef<br>Index
    Note over Client: New/changed sources → "full sources" for which we want all metadata.<br>New/changed items → "partial sources",  we want metadata only for the specified items.
    Client -->> Server: POST /api/v2/sources<br>SourceDelta
    Server ->> Client: SourceMetadata
end
```
