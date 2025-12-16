"""
Tests for the ck3raven resolver module.
"""

import pytest
from ck3raven.resolver.policies import (
    MergePolicy,
    SubBlockPolicy,
    get_policy_for_folder,
    get_content_config,
)


class TestMergePolicy:
    """Test merge policy determination."""
    
    def test_traditions_use_override(self):
        """Traditions should use OVERRIDE policy."""
        policy = get_policy_for_folder("common/culture/traditions")
        assert policy == MergePolicy.OVERRIDE
    
    def test_on_actions_use_container_merge(self):
        """On-actions should use CONTAINER_MERGE policy."""
        policy = get_policy_for_folder("common/on_action")
        assert policy == MergePolicy.CONTAINER_MERGE
    
    def test_defines_use_per_key(self):
        """Defines should use PER_KEY_OVERRIDE policy."""
        policy = get_policy_for_folder("common/defines")
        assert policy == MergePolicy.PER_KEY_OVERRIDE
    
    def test_localization_use_per_key(self):
        """Localization should use PER_KEY_OVERRIDE policy."""
        policy = get_policy_for_folder("localization/english")
        assert policy == MergePolicy.PER_KEY_OVERRIDE
    
    def test_gui_uses_fios(self):
        """GUI should use FIOS policy."""
        policy = get_policy_for_folder("gui")
        assert policy == MergePolicy.FIOS
    
    def test_default_is_override(self):
        """Unknown folders should default to OVERRIDE."""
        policy = get_policy_for_folder("common/unknown_folder")
        assert policy == MergePolicy.OVERRIDE


class TestContentTypeConfig:
    """Test content type configuration."""
    
    def test_tradition_config(self):
        """Tradition config should be present."""
        config = get_content_config("tradition")
        assert config is not None
        assert config.policy == MergePolicy.OVERRIDE
        assert "tradition" in config.file_glob
    
    def test_on_action_config(self):
        """On-action config should have sub-rules."""
        config = get_content_config("on_action")
        assert config is not None
        assert config.policy == MergePolicy.CONTAINER_MERGE
        assert config.sub_rules is not None
        assert "events" in config.sub_rules
        assert config.sub_rules["events"] == SubBlockPolicy.APPEND_LIST
        assert config.sub_rules["effect"] == SubBlockPolicy.SINGLE_SLOT_CONFLICT
    
    def test_unknown_config(self):
        """Unknown content type should return None."""
        config = get_content_config("nonexistent_type")
        assert config is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
