# Shared entries

Connections and datasets created in a collection are shared entries. Use their existing create and get methods, passing `EntryLocation.collection(collection_id)` when creating them.

Use `client.shared_entries` to bind a shared connection to a shared dataset, or a shared connection or dataset to a workbook:

```python
binding = client.shared_entries.bind(
    source_id=connection.id,
    target_id=workbook.id,
    delegation=True,
)
assert binding.is_delegated

for target in client.shared_entries.list(entry_id=connection.id, entry_as="source"):
    print(target)

client.shared_entries.update(source_id=connection.id, target_id=workbook.id, delegation=False)
client.shared_entries.unbind(source_id=connection.id, target_id=workbook.id)
```

`delegation=True` delegates access to the source through the target. With `False`, users need their own access to the source. A binding is required in either case. `get_delegation(source_id=..., target_id=..., binded_workbook_id=...)` reads a binding in an optional workbook context. `list` accepts `entry_as="source"` or `"target"`, `mode="all"`, `"workbooks"`, or `"entries"`, an optional `filter_string`, and `page_size` from 1 to 200.
