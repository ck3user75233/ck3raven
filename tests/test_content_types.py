"""
Tests for content type registry and policy lookup.
"""

import pytest

from ck3raven.resolver import (
    MergePolicy,
    CONTENT_TYPES,
    get_content_type,
    get_content_type_for_path,
    get_policy_for_path,
)


class TestContentTypeRegistry:
    """Test the content types registry."""
    
    def test_registry_not_empty(self):
        """Registry should have many content types."""
        assert len(CONTENT_TYPES) > 100
    
    def test_traditions_in_registry(self):
        """Traditions should be in registry."""
        ct = get_content_type("traditions")
        assert ct is not None
        assert ct.name == "Traditions"
        assert "traditions" in ct.relative_path
    
    def test_on_actions_in_registry(self):
        """On-actions should be in registry."""
        ct = get_content_type("on_actions")
        assert ct is not None
        assert ct.merge_policy == MergePolicy.CONTAINER_MERGE
    
    def test_localization_in_registry(self):
        """Localization should be in registry."""
        ct = get_content_type("localization")
        assert ct is not None
        assert ct.merge_policy == MergePolicy.PER_KEY_OVERRIDE
        assert ct.file_pattern == "*.yml"
    
    def test_gui_in_registry(self):
        """GUI should be in registry with FIOS policy."""
        ct = get_content_type("gui")
        assert ct is not None
        assert ct.merge_policy == MergePolicy.FIOS


class TestPolicyLookup:
    """Test policy lookup by path."""
    
    def test_traditions_override(self):
        """Traditions should use OVERRIDE."""
        policy = get_policy_for_path("common/culture/traditions/00_test.txt")
        assert policy == MergePolicy.OVERRIDE
    
    def test_on_action_container_merge(self):
        """on_action should use CONTAINER_MERGE."""
        policy = get_policy_for_path("common/on_action/yearly.txt")
        assert policy == MergePolicy.CONTAINER_MERGE
    
    def test_defines_per_key(self):
        """Defines should use PER_KEY_OVERRIDE."""
        policy = get_policy_for_path("common/defines/00_defines.txt")
        assert policy == MergePolicy.PER_KEY_OVERRIDE
    
    def test_localization_per_key(self):
        """Localization should use PER_KEY_OVERRIDE."""
        policy = get_policy_for_path("localization/english/test_l_english.yml")
        assert policy == MergePolicy.PER_KEY_OVERRIDE
    
    def test_gui_fios(self):
        """GUI should use FIOS."""
        policy = get_policy_for_path("gui/window_test.gui")
        assert policy == MergePolicy.FIOS
    
    def test_events_override(self):
        """Events should use OVERRIDE."""
        policy = get_policy_for_path("events/my_events.txt")
        assert policy == MergePolicy.OVERRIDE
    
    def test_unknown_path_defaults_override(self):
        """Unknown paths should default to OVERRIDE."""
        policy = get_policy_for_path("some/unknown/path.txt")
        assert policy == MergePolicy.OVERRIDE


class TestContentTypeForPath:
    """Test content type lookup by file path."""
    
    def test_finds_traditions(self):
        """Should find traditions content type."""
        ct = get_content_type_for_path("common/culture/traditions/test.txt")
        assert ct is not None
        assert ct.name == "Traditions"
    
    def test_finds_cultures(self):
        """Should find cultures content type."""
        ct = get_content_type_for_path("common/culture/cultures/test.txt")
        assert ct is not None
        assert ct.name == "Cultures"
    
    def test_finds_most_specific(self):
        """Should find most specific matching content type."""
        # common/culture/traditions is more specific than common/culture
        ct = get_content_type_for_path("common/culture/traditions/00_test.txt")
        assert ct is not None
        assert "traditions" in ct.relative_path
    
    def test_none_for_no_match(self):
        """Should return None for paths with no matching content type."""
        ct = get_content_type_for_path("totally/fake/path.txt")
        assert ct is None


class TestMergePolicyEnum:
    """Test MergePolicy enum values."""
    
    def test_four_policies_exist(self):
        """Should have exactly 4 merge policies."""
        policies = list(MergePolicy)
        assert len(policies) == 4
    
    def test_policy_names(self):
        """Check policy names are correct."""
        names = {p.name for p in MergePolicy}
        expected = {"OVERRIDE", "CONTAINER_MERGE", "PER_KEY_OVERRIDE", "FIOS"}
        assert names == expected
