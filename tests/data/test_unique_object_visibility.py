from tools.data.types.object_visibility import UniqueObjectVisibilityPolicy


def test_one_visibility_policy_covers_every_unique_object_class() -> None:
    policy = UniqueObjectVisibilityPolicy(
        own_owner_refs={"user:testA", "profile:testA-research"},
        direct_subordinate_owner_refs={"user:MaxJJW"},
        shared_object_refs={"product-group:v2:shared"},
    )

    assert policy.scope_for({"owner_ref": "public", "ref": "factor:v2:public"}) == "public"
    assert policy.scope_for({"owner_ref": "user:testA", "ref": "factor:v2:mine"}) == "mine"
    assert policy.scope_for({"owner_ref": "user:MaxJJW", "ref": "product-category:v2:child"}) == "direct_subordinate"
    assert policy.scope_for({"owner_ref": "user:other", "ref": "product-group:v2:shared"}) == "shared_with_me"
    assert policy.scope_for({"owner_ref": "user:other", "ref": "data-source:v2:hidden"}) is None
