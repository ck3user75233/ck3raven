Fix 1: language_mehri → language_south_arabian
File: MiniSuperCompatch/common/scripted_effects/zzz_msc_ce_s_arab_scripted_effects.txt

Replace entire file with:

# Mini Super Compatch - Culture Expanded South Arabian fix
# Fixes: unlearn_language called without checking if culture has heritage_arabic
# This patch adds the heritage check to prevent Arabic speakers with Arabic heritage from losing their language
#
# Overrides from: Culture Expanded - ce_s_arab_scripted_effects.txt
# Fixed: language_mehri -> language_south_arabian (language_mehri doesn't exist)

make_mahri_culture_effect = {
    set_culture = culture:mahri
    if = {
        limit = {
            knows_language = language_arabic
            NOT = { culture = { has_cultural_pillar = heritage_arabic } }
        }
        unlearn_language = language_arabic
    }
    if = {
        limit = { NOT = { knows_language = language_south_arabian } }
        learn_language = language_south_arabian
    }
}

make_south_arabian_culture_effect = {
    set_culture = culture:south_arabian
    if = {
        limit = {
            knows_language = language_arabic
            NOT = { culture = { has_cultural_pillar = heritage_arabic } }
        }
        unlearn_language = language_arabic
    }
    if = {
        limit = { NOT = { knows_language = language_south_arabian } }
        learn_language = language_south_arabian
    }
}

Fix 2: ADVCM poet trait fix (NEW FILE)
Create: MiniSuperCompatch/common/scripted_guis/zzz_msc_advcm_cc_presets_sgui.txt

# Mini Super Compatch - Advanced Cheat Menu poet trait fix
# Fixes: trait:poet -> trait:lifestyle_poet (poet is not a valid trait ID)
#
# Partial override for: Advanced Cheat Menu - advcm_cc_presets_sgui.txt

advcm_cc_court_jester_sgui = {
    scope = character

    effect = {

        clear_variable_list = advcm_character_spawner_traits_list
        advcm_cc_reset_skill_effect = yes

        set_variable = {
            name = advcm_character_spawner_diplomacy
            value = 20
        }

        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:education_diplomacy_5 }
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:stubborn}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:diligent}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:gregarious}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:shrewd}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:lifestyle_poet}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:athletic}
    }
}

advcm_cc_court_poet_sgui = {
    scope = character

    effect = {

        clear_variable_list = advcm_character_spawner_traits_list
        advcm_cc_reset_skill_effect = yes

        set_variable = {
            name = advcm_character_spawner_diplomacy
            value = 20
        }

        set_variable = {
            name = advcm_character_spawner_learning
            value = 20
        }

        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:education_diplomacy_5 }
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:stubborn}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:diligent}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:gregarious}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:lifestyle_poet}
    }
}

advcm_cc_court_musician_sgui = {
    scope = character

    effect = {

        clear_variable_list = advcm_character_spawner_traits_list
        advcm_cc_reset_skill_effect = yes

        set_variable = {
            name = advcm_character_spawner_diplomacy
            value = 20
        }

        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:education_diplomacy_5 }
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:stubborn}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:diligent}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:gregarious}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:lifestyle_poet}
    }
}

advcm_cc_chronicler_sgui = {
    scope = character

    effect = {

        clear_variable_list = advcm_character_spawner_traits_list
        advcm_cc_reset_skill_effect = yes

        set_variable = {
            name = advcm_character_spawner_learning
            value = 25
        }
        set_variable = {
            name = advcm_character_spawner_diplomacy
            value = 25
        }

        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:education_learning_5 }
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:honest}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:diligent}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:gregarious}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:diplomat}
        add_to_variable_list = { name = advcm_character_spawner_traits_list target = trait:lifestyle_poet}
    }
}

Fix 3: FSF Browse the Bookstore poet trait fix (NEW FILE)
Create: MiniSuperCompatch/events/zzz_msc_fsf_btb_shelf_event.txt

# Mini Super Compatch - [FSF] Browse the Bookstore poet trait fix
# Fixes: has_trait = poet -> has_trait = lifestyle_poet
#        add_trait = poet -> add_trait = lifestyle_poet
#
# Partial override for: [FSF] Browse the Bookstore - fsf_btb_shelf_event.txt

namespace = fsf_btb_shelf

#Browse Education Section - FIXED poet references
fsf_btb_shelf.0100 = {
    type = character_event
    title = fsf_btb_shelf.0100.title
    desc = fsf_btb_shelf.0100.desc
    theme = education
    
    
    left_portrait = {
        character = scope:fsf_btb
        animation = personality_rational
    }

    option = { # Gardener
        trigger = {
            NOR = {
            has_trait = lifestyle_gardener
            }
        }
        name = fsf_btb_shelf.1004.title
        custom_tooltip = fsf_btb_shelf.1004.tooltip
        show_as_tooltip = {
            add_trait = lifestyle_gardener
        }
        remove_short_term_gold = 150
        trigger_event = fsf_btb_book.1004
        }

    option = { # Herbalist
        trigger = {
            NOR = {
            has_trait = lifestyle_herbalist
            }
        }
        name = fsf_btb_shelf.1005.title
        custom_tooltip = fsf_btb_shelf.1005.tooltip
        show_as_tooltip = {
            add_trait = lifestyle_herbalist
        }
        remove_short_term_gold = 125
        trigger_event = fsf_btb_book.1005
        }

    option = { # Poet - FIXED: poet -> lifestyle_poet
        trigger = {
            NOR = {
            has_trait = lifestyle_poet
            }
        }
        name = fsf_btb_shelf.1006.title
        custom_tooltip = fsf_btb_shelf.1006.tooltip
        show_as_tooltip = {
            add_trait = lifestyle_poet
        }
        remove_short_term_gold = 100
        trigger_event = fsf_btb_book.1006
    }

    option = { # Return to Main Browsing
        name = fsf_btb_shelf.0001.return
        trigger_event = fsf_btb_shelf.0001
    }
}

Bug Reports
Bug 1: ck3lens mode has NO write permissions
Policy claims:

write_allowed: ["mods[] under local_mods_folder", "wip_workspace"]
Reality:

Local mod write → EN-WRITE-D-001: ROOT_USER_DOCS
WIP write → EN-WRITE-D-001: ROOT_CK3RAVEN_DATA
Root cause: Policy enforcement categorizes by broad path roots without checking allowed subdirectories.

Bug 2: Extension shows wrong mode
Actual MCP server mode: ck3lens (confirmed by ck3_get_detected_mode)
Extension UI shows: ck3raven-dev

Possible cause: Mode is persisted to a file that the other VS Code window wrote, and this window's extension reads that file instead of querying its own MCP server instance.

Claude Opus 4.5 • 3x