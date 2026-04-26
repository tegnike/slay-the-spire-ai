"""Static policy data for the Slay the Spire AI."""

import re

SEED_ALPHABET = "0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
SEED_RE = re.compile(r"^[0-9A-Z]+$")

ATTACK_PRIORITY = {
    "Bash": 100,
    "Strike_R": 80,
    "Strike_G": 80,
    "Strike_B": 80,
    "Strike_P": 80,
    "Strike": 75,
}

BLOCK_PRIORITY = {
    "Defend_R": 90,
    "Defend_G": 90,
    "Defend_B": 90,
    "Defend_P": 90,
    "Defend": 85,
}

CARD_REWARD_PRIORITY = {
    "Shockwave": 140,
    "Offering": 135,
    "Immolate": 130,
    "Feed": 125,
    "Bludgeon": 122,
    "Fiend Fire": 120,
    "Reaper": 115,
    "Corruption": 105,
    "Demon Form": 100,
    "Inflame": 96,
    "Disarm": 94,
    "Carnage": 92,
    "Whirlwind": 91,
    "Uppercut": 90,
    "Shrug It Off": 88,
    "Battle Trance": 86,
    "Pommel Strike": 82,
    "Hemokinesis": 80,
    "Twin Strike": 78,
    "Wild Strike": 77,
    "Clothesline": 76,
    "Headbutt": 74,
    "True Grit": 72,
    "Thunderclap": 70,
    "Anger": 68,
    "Cleave": 66,
    "Armaments": 64,
    "Second Wind": 63,
    "Seeing Red": 62,
    "Body Slam": 35,
    "Dual Wield": 30,
}

SHOP_CARD_PRIORITY = {
    **CARD_REWARD_PRIORITY,
    "Membership Card": 120,
    "Pen Nib": 115,
    "Pocketwatch": 95,
    "Gambler's Brew": 70,
    "Explosive Potion": 58,
    "Dexterity Potion": 45,
}

CARD_BASE_DAMAGE = {
    "Strike_R": 6,
    "Strike_G": 6,
    "Strike_B": 6,
    "Strike_P": 6,
    "Strike": 6,
    "Bash": 8,
    "Anger": 6,
    "Pommel Strike": 9,
    "Headbutt": 9,
    "Clothesline": 12,
    "Cleave": 8,
    "Thunderclap": 4,
    "Uppercut": 13,
    "Carnage": 20,
    "Hemokinesis": 15,
    "Immolate": 21,
    "Bludgeon": 32,
    "Fiend Fire": 21,
    "Reaper": 4,
    "Whirlwind": 15,
    "Twin Strike": 10,
    "Wild Strike": 12,
    "Clash": 14,
    "Sword Boomerang": 9,
    "Perfected Strike": 12,
    "Iron Wave": 5,
    "Searing Blow": 12,
    "Sever Soul": 16,
    "Blood for Blood": 18,
    "Dropkick": 5,
    "Heavy Blade": 14,
    "Pummel": 8,
    "Rampage": 8,
    "Reckless Charge": 7,
}

CARD_BASE_BLOCK = {
    "Defend_R": 5,
    "Defend_G": 5,
    "Defend_B": 5,
    "Defend_P": 5,
    "Defend": 5,
    "Shrug It Off": 8,
    "True Grit": 7,
    "Armaments": 5,
    "Iron Wave": 5,
    "Flame Barrier": 12,
    "Power Through": 15,
    "Ghostly Armor": 10,
    "Impervious": 30,
    "Entrench": 0,
    "Second Wind": 10,
    "Sentinel": 5,
    "Rage": 3,
}

FRONTLOAD_ATTACKS = {
    "Anger",
    "Bludgeon",
    "Carnage",
    "Cleave",
    "Clothesline",
    "Feed",
    "Hemokinesis",
    "Immolate",
    "Pommel Strike",
    "Sever Soul",
    "Thunderclap",
    "Twin Strike",
    "Uppercut",
    "Whirlwind",
    "Wild Strike",
}

SPECULATIVE_SYNERGY_CARDS = {
    "Barricade",
    "Body Slam",
    "Corruption",
    "Dark Embrace",
    "Dual Wield",
    "Feel No Pain",
    "Fire Breathing",
    "Juggernaut",
    "Rupture",
}

REWARD_PRIORITY = {
    "RELIC": 120,
    "CARD": 100,
    "GOLD": 90,
    "STOLEN_GOLD": 88,
    "POTION": 70,
    "EMERALD_KEY": 30,
    "SAPPHIRE_KEY": 25,
}
