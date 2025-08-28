# leaderboard.py

from telegram.ext import ContextTypes
# Make sure drive_utils is available to this file
from drive_utils import get_drive_service, get_folder_id, count_all_files_for_branch
import config

def get_leaderboard_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    Queries the database and returns a formatted string for the dynamic leaderboard.
    """
    db = context.application.persistence.db
    
    pipeline = [
        {"$match": {"data.points": {"$exists": True}}},
        {"$sort": {"data.points": -1}},
        {"$limit": 10}
    ]
    top_users = list(db["user_data"].aggregate(pipeline))
    
    if not top_users:
        return "The leaderboard is empty. Start downloading files to get points!"

    leaderboard_text = "🏆 *Top 10 Study Champions*\n_(Score based on your branch's total files)_\n\n"
    rank_emojis = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    
    service = get_drive_service()
    if not service:
        return "Could not connect to Google Drive to calculate total points."

    for i, user_doc in enumerate(top_users):
        user_data = user_doc.get("data", {})
        name = user_data.get("name", "A User")
        points = user_data.get("points", 0)
        year = user_data.get("year")
        branch = user_data.get("branch")

        max_points = 0
        if year and branch:
            # Find the user's branch folder ID to count files
            year_folder_name = year.replace(" ", "_")
            year_id = get_folder_id(service, config.GOOGLE_DRIVE_ROOT_FOLDER_ID, year_folder_name)
            if year_id:
                branch_id = get_folder_id(service, year_id, branch)
                if branch_id:
                    notes_count, assignments_count = count_all_files_for_branch(service, branch_id)
                    max_points = (notes_count * 1) + (assignments_count * 2)

        if max_points > 0:
            percentage = (points / max_points) * 100
            score = f"{points}/{max_points} points ({percentage:.0f}%)"
        else:
            score = f"{points} points"
        
        leaderboard_text += f"{rank_emojis[i]} *{name}* - {score}\n"
        
    return leaderboard_text
