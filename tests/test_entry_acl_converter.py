from __future__ import annotations

from pydantic import ValidationError
import pytest

from datalens_sdk.converter.entry_acl import EntryAclSuggestionsConverter
from datalens_sdk.domain.permissions import EntryPermissionSubject


def test_suggestions_use_array_root_and_preserve_incomplete_metadata() -> None:
    assert EntryAclSuggestionsConverter.payload("name") == {"searchText": "name"}
    assert EntryAclSuggestionsConverter.result([{}, {"title": "display only", "__rlsid": "rls", "future": True}]) == (
        EntryPermissionSubject(),
        EntryPermissionSubject(title="display only", rls_id="rls"),
    )
    with pytest.raises(ValidationError):
        EntryAclSuggestionsConverter.result({"subjects": []})
