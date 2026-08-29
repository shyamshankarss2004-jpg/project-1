"""
tools/python_translate.py
--------------------------
One-time migration script: translated Polish database values to English.

This script has already been run (the database has been updated).
It is preserved here for documentation purposes only.

DO NOT run this script again – it will attempt to rename already-translated
values and may cause data inconsistencies.
"""

import sqlite3
from utils.resource_helper import resource_path

# Mapping of Polish names → English equivalents used in the initial migration
TRANSLATIONS = {
    "muscle_group": {
        "Belly": "Abs",
        "Hands": "Arms",
        "Cage": "Chest",
        "Whole body": "Full Body",
    },
    "exercises": {
        "Pumps": "Push-ups",
        "Romes": "Jumping Jacks",
        "Pull -up": "Pull-up",
        "Pumps on handrails": "Dips",
        "Squeezing above the head": "Overhead Press",
        "Biceps deflections": "Bicep Curls",
        "Floor Flys": "Chest Flys",
        "Single-Lean Squats": "Single-leg Squats",
        "TRIRCEP Extensions in Plank": "Tricep Extensions in Plank",
        "Arm Raises front": "Front Arm Raises",
        "Arm Raises in Plank": "Plank Arm Raises",
    },
    "workout_plans": {
        "Camera training": "Form Training",
        "Strengthening the whole body": "Full Body Strength",
        "Strength and endurance": "Strength & Endurance",
        "Strong arms and chest": "Arms & Chest",
        "Strong legs and buttocks": "Legs & Glutes",
    },
}


def main():
    db_path = resource_path("data/database.db")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for table, mapping in TRANSLATIONS.items():
            for old_name, new_name in mapping.items():
                cursor.execute(
                    f"UPDATE {table} SET name = ? WHERE name = ?",
                    (new_name, old_name),
                )
        conn.commit()
    print("✅ Database updated with English names.")


if __name__ == "__main__":
    main()
