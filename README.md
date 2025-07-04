# data.all core package

This is a package containing dataall_core modules used in both data.all CLI and SDK.


# generate schema from a data.all deployments

* Copy and run the following script in `data.all/backend` directory...
```python
from dataall.base.loader import load_modules, ImportMode
from graphql import introspection_from_schema
from dataall.base.api import get_executable_schema
import json

load_modules(modes={ImportMode.API})
SCHEMA = get_executable_schema()
t = introspection_from_schema(SCHEMA)

# Write schema to JSON file
with open('./schema.json', 'w') as f:
f.write(json.dumps(t))
```

