import sqlite3

db_path = "data/database.db"  # adjust if needed

translations = {
    "muscle_group": {
        "Belly": "Abs",
        "Hands": "Arms",
        "Cage": "Chest",
        "Whole body": "Full Body"
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
        "Arm Raises in Plank": "Plank Arm Raises"
    },
    "workout_plans": {
        "Camera training": "Form Training",
        "Strengthening the whole body": "Full Body Strength",
        "Strength and endurance": "Strength & Endurance",
        "Strong arms and chest": "Arms & Chest",
        "Strong legs and buttocks": "Legs & Glutes"
    }
}

with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    for table, mapping in translations.items():
        for old, new in mapping.items():
            cursor.execute(f"UPDATE {table} SET name = ? WHERE name = ?", (new, old))
    conn.commit()

print("✅ Database updated with English names!")
