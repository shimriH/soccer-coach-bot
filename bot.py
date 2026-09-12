#!/usr/bin/env python3
"""
בוט טלגרם מתקדם למאמני כדורגל - בניית מערכי אימון שבועיים
מיקוד: חשיבה, סריקה, ראש למעלה, פעולות לפי היריב
שנתונים: 2013 ו-2018 | 11 שחקנים | 90 דקות
"""

import logging
import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import random

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ==================== הגדרות ====================
# לקריאה ממשתנה סביבה (Railway) או ישירות
BOT_TOKEN = os.getenv("BOT_TOKEN") or "הכנס_כאן_את_הטוקן_שלך"

# מצבי שיחה
(
    CHOOSING_AGE,
    CHOOSING_SESSIONS,
    ENTERING_FOCUS,
    ENTERING_SECONDARY,
    CONFIRMING,
    EDITING,
) = range(6)

# ==================== מסד נתונים ====================
def init_db():
    conn = sqlite3.connect("coach_bot.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            age_group TEXT DEFAULT '2013',
            players INTEGER DEFAULT 11,
            session_minutes INTEGER DEFAULT 90,
            sessions_per_week INTEGER DEFAULT 3,
            created_at TEXT,
            last_active TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            week_start TEXT,
            age_group TEXT,
            main_focus TEXT,
            secondary_focus TEXT,
            plan_json TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    """)
    conn.commit()
    conn.close()


def get_user(user_id: int) -> Dict:
    conn = sqlite3.connect("coach_bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "age_group": row[1],
            "players": row[2],
            "session_minutes": row[3],
            "sessions_per_week": row[4],
        }
    return None


def save_user(user_id: int, **kwargs):
    conn = sqlite3.connect("coach_bot.db")
    c = conn.cursor()
    existing = get_user(user_id)
    now = datetime.now().isoformat()
    if existing:
        updates = []
        values = []
        for key, value in kwargs.items():
            updates.append(f"{key} = ?")
            values.append(value)
        values.append(now)
        values.append(user_id)
        c.execute(
            f"UPDATE users SET {', '.join(updates)}, last_active = ? WHERE user_id = ?",
            values,
        )
    else:
        c.execute(
            """
            INSERT INTO users (user_id, age_group, players, session_minutes, sessions_per_week, created_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                kwargs.get("age_group", "2013"),
                kwargs.get("players", 11),
                kwargs.get("session_minutes", 90),
                kwargs.get("sessions_per_week", 3),
                now,
                now,
            ),
        )
    conn.commit()
    conn.close()


def save_plan(user_id: int, age_group: str, main_focus: str, secondary_focus: str, plan: Dict):
    conn = sqlite3.connect("coach_bot.db")
    c = conn.cursor()
    week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
    c.execute(
        """
        INSERT INTO weekly_plans (user_id, week_start, age_group, main_focus, secondary_focus, plan_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            week_start,
            age_group,
            main_focus,
            secondary_focus,
            json.dumps(plan, ensure_ascii=False),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_last_plans(user_id: int, limit: int = 5) -> List[Dict]:
    conn = sqlite3.connect("coach_bot.db")
    c = conn.cursor()
    c.execute(
        """
        SELECT id, week_start, age_group, main_focus, secondary_focus, created_at
        FROM weekly_plans WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
        """,
        (user_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "week_start": r[1],
            "age_group": r[2],
            "main_focus": r[3],
            "secondary_focus": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


# ==================== מחולל מערכים ====================
class PlanGenerator:
    """מחולל מערכי אימון מבוסס תבניות חכמות עם התאמה לדגשים"""

    DRILLS = {
        "scanning": [
            {
                "name": "צבעים בראש למעלה",
                "desc": "כדרור חופשי + זיהוי צבע שהמאמן מרים. רץ לקונוס הנכון.",
                "setup": "ריבוע 15-20מ', 4 קונוסים צבעוניים, כדור לכל שחקן",
                "points": ["ראש למעלה לפני שינוי כיוון", "זיהוי מהיר בלי לעצור את הכדור", "לא להסתכל רק על הכדור"],
                "animation": "שחקנים כדרורים → מאמן מרים צבע → סריקה → ריצה לקונוס → חזרה",
            },
            {
                "name": "סרוק לפני קבלה",
                "desc": "מסירה למקבל. המקבל חייב לסרוק (כתף/שמאל-ימין) לפני הנגיעה הראשונה ולקרוא מה ראה.",
                "setup": "3-4 קבוצות קטנות, שחקן מרכז + מסביב",
                "points": ["סריקה לפני שהכדור מגיע", "גוף פתוח", "החלטה לפי מה שראית"],
                "animation": "מסירה בדרך → סריקה → קבלה → החלטה (מסירה/סיבוב/כדרור) → מסירה הלאה",
            },
            {
                "name": "רונדו עם חובת סריקה",
                "desc": "4v2 או 5v2. לפני קבלה חייבים לקרוא בקול מה רואים (לחץ/פנוי).",
                "setup": "ריבוע 12-15מ', 2 לוחצים",
                "points": ["אין מסירה אוטומטית", "קריאה בקול לפני קבלה", "החלטה לפי מיקום הלוחצים"],
                "animation": "כדור בחוץ → סריקה + קריאה → קבלה → מסירה חכמה → רוטציה",
            },
        ],
        "decision": [
            {
                "name": "2v1 עם החלטה",
                "desc": "שני תוקפים מול מגן אחד. התוקף עם הכדור מחליט: מסירה או חדירה לפי מיקום המגן.",
                "setup": "ערוץ 10x20מ', שערון קטן",
                "points": ["ראש למעלה לפני ההחלטה", "לפי היריב – לא אוטומטי", "תזמון המסירה"],
                "animation": "כדור נכנס → סריקה של המגן → החלטה → ביצוע → סיום",
            },
            {
                "name": "3v2 מעבר מהיר",
                "desc": "שלושה תוקפים מול שני מגנים. חייבים למצוא את השחקן החופשי לפי הלחץ.",
                "setup": "שטח 20x25מ', שני שערונים",
                "points": ["סריקה של כל השחקנים", "מסירה לשחקן הפנוי", "לא לשחק ללחץ"],
                "animation": "בנייה → זיהוי יתרון → מסירה חכמה → סיום",
            },
            {
                "name": "בחירת פעולה לפי לחץ",
                "desc": "שחקן מקבל כדור עם לחץ משתנה (קרוב/רחוק/מהצד). חייב לבחור פעולה שונה בכל פעם.",
                "setup": "ריבוע קטן + שחקן לחץ",
                "points": ["זיהוי סוג הלחץ", "פעולה שונה לכל מצב", "מהירות החלטה"],
                "animation": "קבלה → זיהוי לחץ → בחירה (מסירה/סיבוב/הגנה על הכדור) → ביצוע",
            },
        ],
        "1v1": [
            {
                "name": "1v1 עם סריקה מוקדמת",
                "desc": "תוקף מקבל כדור ויודע מראש מאיפה המגן מגיע (או צריך לזהות). מחליט לפי המיקום.",
                "setup": "ערוץ צר, שערון",
                "points": ["סריקה לפני קבלה", "שימוש בגוף", "שינוי קצב"],
                "animation": "מסירה → סריקה → קבלה לכיוון הנכון → 1v1 → סיום",
            },
            {
                "name": "1v1 דו-כיווני",
                "desc": "אפשר לסיים לשני כיוונים. התוקף בוחר לפי מיקום המגן.",
                "setup": "שני שערונים קטנים",
                "points": ["ראש למעלה", "החלטה לפי היריב", "שינוי כיוון מהיר"],
                "animation": "כניסה → סריקה → בחירת צד → חדירה/מסירה דמה",
            },
        ],
        "possession": [
            {
                "name": "שמירת כדור עם חובת פתיחה",
                "desc": "4v4 או 5v5. אי אפשר למסור אחורה פעמיים ברצף. חייבים לחפש פתיחה.",
                "setup": "שטח בינוני",
                "points": ["סריקה לחיפוש שחקן פנוי", "לא לשחק אוטומטית אחורה", "תנועה אחרי מסירה"],
                "animation": "מסירה → סריקה → פתיחה קדימה/לצד → תמיכה",
            },
            {
                "name": "רונדו 6v3 עם מעבר",
                "desc": "כשהכדור נכבש – מעבר מהיר להתקפה על שערונים.",
                "setup": "ריבוע + שני שערונים",
                "points": ["סריקה בזמן ההגנה", "מעבר מהיר אחרי זכייה", "החלטה לאן לתקוף"],
                "animation": "שמירה → זכייה → סריקה מהירה → מעבר → סיום",
            },
        ],
    }

    AGE_ADJUST = {
        "2018": {
            "space": "שטחים גדולים יותר, פחות לחץ בהתחלה",
            "rules": "פחות חוקים מורכבים, יותר משחק וכיף",
            "language": "שפה פשוטה, הדגמה רבה",
        },
        "2013": {
            "space": "שטחים קטנים יותר, לחץ אמיתי",
            "rules": "חוקים שדורשים חשיבה (קריאה בקול, מגבלות מסירה)",
            "language": "שאלות מעמיקות, אחריות אישית",
        },
    }

    def generate_weekly_plan(
        self,
        age_group: str,
        sessions: int,
        main_focus: str,
        secondary_focus: str = "",
        players: int = 11,
    ) -> Dict:
        focus_key = self._map_focus(main_focus)
        secondary_key = self._map_focus(secondary_focus) if secondary_focus else None

        plan = {
            "age_group": age_group,
            "players": players,
            "sessions_count": sessions,
            "main_focus": main_focus,
            "secondary_focus": secondary_focus,
            "week_theme": f"שיפור {main_focus}" + (f" + {secondary_focus}" if secondary_focus else ""),
            "coach_tips": self._get_coach_tips(age_group, main_focus),
            "sessions": [],
        }

        for i in range(sessions):
            session = self._generate_session(
                session_num=i + 1,
                age_group=age_group,
                focus_key=focus_key,
                secondary_key=secondary_key if i % 2 == 1 else None,
                players=players,
            )
            plan["sessions"].append(session)

        return plan

    def _map_focus(self, text: str) -> str:
        text = text.lower()
        if any(w in text for w in ["סריקה", "ראש", "scanning", "ראייה", "מבט"]):
            return "scanning"
        if any(w in text for w in ["החלטה", "decision", "חשיבה", "בחירה", "לפי היריב"]):
            return "decision"
        if any(w in text for w in ["1v1", "אחד על אחד", "דריבל", "חדירה"]):
            return "1v1"
        if any(w in text for w in ["שמירה", "possession", "רונדו", "החזקה"]):
            return "possession"
        return "decision"

    def _generate_session(self, session_num: int, age_group: str, focus_key: str, secondary_key: Optional[str], players: int) -> Dict:
        drills_pool = self.DRILLS.get(focus_key, self.DRILLS["decision"])[:]
        if secondary_key and secondary_key in self.DRILLS:
            drills_pool += self.DRILLS[secondary_key][:1]

        selected = random.sample(drills_pool, min(3, len(drills_pool)))

        adjust = self.AGE_ADJUST.get(age_group, self.AGE_ADJUST["2013"])

        session = {
            "number": session_num,
            "title": f"אימון {session_num} – {focus_key}",
            "duration": 90,
            "structure": [
                {"phase": "חימום + סריקה", "time": "15 דק'", "content": selected[0]["name"]},
                {"phase": "תרגיל מרכזי 1", "time": "20 דק'", "content": selected[1]["name"] if len(selected) > 1 else selected[0]["name"]},
                {"phase": "תרגיל מרכזי 2 / משחק קטן", "time": "25 דק'", "content": selected[2]["name"] if len(selected) > 2 else "משחק 5v5 עם חוק סריקה"},
                {"phase": "משחק חופשי / סיום", "time": "20 דק'", "content": "משחק עם דגש על הנושא + שאלות"},
                {"phase": "סיכום + מתיחה", "time": "10 דק'", "content": "שיחה קצרה + שאלות לשחקנים"},
            ],
            "drills": selected,
            "age_notes": adjust,
            "key_questions": [
                "מה ראית לפני שקיבלת את הכדור?",
                "למה בחרת בפעולה הזו?",
                "איפה היה הלחץ / השחקן הפנוי?",
                "האם ההחלטה הייתה אוטומטית או לפי מה שראית?",
            ],
        }
        return session

    def _get_coach_tips(self, age_group: str, focus: str) -> List[str]:
        tips = [
            "עצור את התרגיל ושאל שאלות במקום לתת הוראות ישירות.",
            "תן לשחקנים לטעות – הלמידה קורה מהטעויות.",
            "השתמש בשפה של 'מה ראית?' במקום 'הרם ראש!'.",
            "תעד לעצמך אחרי כל אימון: מי שיפר סריקה? מי עדיין אוטומטי?",
        ]
        if age_group == "2018":
            tips.append("בגיל הזה – הרבה הדגמה, מעט דיבור, הרבה חזרות מהנות.")
        else:
            tips.append("בגיל 13 – תן להם אחריות: שיסבירו אחד לשני מה ראו.")
        return tips


# ==================== Handlers ====================
generator = PlanGenerator()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id)

    text = (
        f"שלום {user.first_name}! 👋\n\n"
        "אני הבוט שלך לבניית **מערכי אימון שבועיים** חכמים.\n\n"
        "המיקוד שלי:\n"
        "• חשיבה במקום לחץ אוטומטי\n"
        "• ראש למעלה + סריקה\n"
        "• פעולות לפי היריב\n"
        "• שיפור כקבוצה + כבודדים + אתה כמאמן\n\n"
        "בוא נתחיל לבנות מערך שבועי."
    )

    keyboard = [
        [InlineKeyboardButton("📅 בנה מערך שבועי חדש", callback_data="new_weekly")],
        [InlineKeyboardButton("⚙️ הגדרות שלי", callback_data="settings")],
        [InlineKeyboardButton("📜 היסטוריית מערכים", callback_data="history")],
        [InlineKeyboardButton("❓ עזרה", callback_data="help")],
    ]
    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "new_weekly":
        await query.edit_message_text(
            "בחר שנתון לאימון השבועי:",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("שנתון 2013 (בני ~13)", callback_data="age_2013")],
                    [InlineKeyboardButton("שנתון 2018 (בני ~8)", callback_data="age_2018")],
                    [InlineKeyboardButton("שניהם (מערכים נפרדים)", callback_data="age_both")],
                ]
            ),
        )
        return CHOOSING_AGE

    elif data.startswith("age_"):
        age = data.replace("age_", "")
        context.user_data["age_group"] = age
        save_user(user_id, age_group=age if age != "both" else "2013")

        await query.edit_message_text(
            "כמה אימונים בשבוע תרצה במערך?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("2", callback_data="sess_2"),
                        InlineKeyboardButton("3", callback_data="sess_3"),
                        InlineKeyboardButton("4", callback_data="sess_4"),
                    ]
                ]
            ),
        )
        return CHOOSING_SESSIONS

    elif data.startswith("sess_"):
        sessions = int(data.replace("sess_", ""))
        context.user_data["sessions"] = sessions
        save_user(user_id, sessions_per_week=sessions)

        await query.edit_message_text(
            "מה ה**דגש המרכזי** של השבוע?\n\n"
            "כתוב בחופשיות, למשל:\n"
            "• סריקה וראש למעלה\n"
            "• קבלת החלטות לפי היריב\n"
            "• 1v1 + חשיבה\n"
            "• שמירת כדור חכמה\n\n"
            "פשוט שלח הודעה עם הדגש:",
            parse_mode="Markdown",
        )
        return ENTERING_FOCUS

    elif data == "settings":
        user = get_user(user_id) or {}
        text = (
            f"**ההגדרות שלך:**\n\n"
            f"• שנתון: {user.get('age_group', '2013')}\n"
            f"• מספר שחקנים: {user.get('players', 11)}\n"
            f"• משך אימון: {user.get('session_minutes', 90)} דקות\n"
            f"• אימונים בשבוע: {user.get('sessions_per_week', 3)}\n"
        )
        await query.edit_message_text(text, parse_mode="Markdown")

    elif data == "history":
        plans = get_last_plans(user_id)
        if not plans:
            await query.edit_message_text("עדיין אין מערכים שמורים. בנה את הראשון!")
            return
        text = "**המערכים האחרונים שלך:**\n\n"
        for p in plans:
            text += f"• {p['week_start']} | {p['age_group']} | {p['main_focus']}\n"
        await query.edit_message_text(text, parse_mode="Markdown")

    elif data == "help":
        text = (
            "**איך משתמשים בבוט?**\n\n"
            "1. לחץ על 'בנה מערך שבועי חדש'\n"
            "2. בחר שנתון ומספר אימונים\n"
            "3. כתוב את הדגשים שלך לשבוע\n"
            "4. קבל מערך מלא עם תרגילים, דגשים וטיפים למאמן"
        )
        await query.edit_message_text(text, parse_mode="Markdown")

    elif data == "confirm_plan":
        age = context.user_data.get("age_group", "2013")
        sessions = context.user_data.get("sessions", 3)
        main_focus = context.user_data.get("main_focus", "סריקה וקבלת החלטות")
        secondary = context.user_data.get("secondary_focus", "")

        if age == "both":
            plan_2013 = generator.generate_weekly_plan("2013", sessions, main_focus, secondary)
            plan_2018 = generator.generate_weekly_plan("2018", sessions, main_focus, secondary)
            save_plan(user_id, "2013", main_focus, secondary, plan_2013)
            save_plan(user_id, "2018", main_focus, secondary, plan_2018)
            text = format_plan(plan_2013) + "\n\n" + "─" * 30 + "\n\n" + format_plan(plan_2018)
        else:
            plan = generator.generate_weekly_plan(age, sessions, main_focus, secondary)
            save_plan(user_id, age, main_focus, secondary, plan)
            text = format_plan(plan)

        if len(text) > 4000:
            parts = [text[i : i + 4000] for i in range(0, len(text), 4000)]
            await query.edit_message_text(parts[0], parse_mode="Markdown")
            for part in parts[1:]:
                await context.bot.send_message(chat_id=query.message.chat_id, text=part, parse_mode="Markdown")
        else:
            await query.edit_message_text(text, parse_mode="Markdown")

        keyboard = [
            [InlineKeyboardButton("🔄 מערך חדש", callback_data="new_weekly")],
            [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main_menu")],
        ]
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="מה תרצה לעשות עכשיו?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    elif data == "main_menu":
        await start_from_callback(query, context)
        return ConversationHandler.END

    return ConversationHandler.END


async def start_from_callback(query, context):
    text = "תפריט ראשי:\n\nבחר פעולה:"
    keyboard = [
        [InlineKeyboardButton("📅 בנה מערך שבועי חדש", callback_data="new_weekly")],
        [InlineKeyboardButton("⚙️ הגדרות", callback_data="settings")],
        [InlineKeyboardButton("📜 היסטוריה", callback_data="history")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def receive_focus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    focus = update.message.text.strip()
    context.user_data["main_focus"] = focus

    await update.message.reply_text(
        f"הדגש המרכזי נשמר: **{focus}**\n\n"
        "יש דגש משני? (אופציונלי)\n"
        "אם אין – כתוב 'אין' או שלח /skip",
        parse_mode="Markdown",
    )
    return ENTERING_SECONDARY


async def receive_secondary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["אין", "לא", "no", "/skip", "skip"]:
        context.user_data["secondary_focus"] = ""
    else:
        context.user_data["secondary_focus"] = update.message.text.strip()

    age = context.user_data.get("age_group", "2013")
    sessions = context.user_data.get("sessions", 3)
    main_f = context.user_data.get("main_focus", "")
    sec_f = context.user_data.get("secondary_focus", "אין")

    summary = (
        f"**סיכום לפני יצירה:**\n\n"
        f"• שנתון: {age}\n"
        f"• מספר אימונים: {sessions}\n"
        f"• דגש מרכזי: {main_f}\n"
        f"• דגש משני: {sec_f}\n\n"
        "לאשר וליצור את המערך השבועי?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ כן, צור מערך", callback_data="confirm_plan"),
            InlineKeyboardButton("❌ ביטול", callback_data="main_menu"),
        ]
    ]
    await update.message.reply_text(
        summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return CONFIRMING


def format_plan(plan: Dict) -> str:
    text = f"📋 **מערך שבועי – שנתון {plan['age_group']}**\n"
    text += f"🎯 נושא: {plan['week_theme']}\n"
    text += f"👥 {plan['players']} שחקנים | {plan['sessions_count']} אימונים\n\n"

    text += "🧠 **טיפים לך כמאמן:**\n"
    for tip in plan["coach_tips"]:
        text += f"• {tip}\n"
    text += "\n"

    for session in plan["sessions"]:
        text += f"{'═' * 20}\n"
        text += f"**אימון {session['number']}** ({session['duration']} דק')\n\n"

        text += "**מבנה:**\n"
        for phase in session["structure"]:
            text += f"• {phase['phase']} ({phase['time']}): {phase['content']}\n"
        text += "\n"

        text += "**תרגילים עיקריים:**\n"
        for i, drill in enumerate(session["drills"], 1):
            text += f"\n**{i}. {drill['name']}**\n"
            text += f"{drill['desc']}\n"
            text += f"_הכנה:_ {drill['setup']}\n"
            text += "**דגשים:**\n"
            for p in drill["points"]:
                text += f"  – {p}\n"
            text += f"_אנימציה:_ {drill['animation']}\n"

        text += "\n**שאלות לשאול את השחקנים:**\n"
        for q in session["key_questions"]:
            text += f"• {q}\n"
        text += f"\n_התאמה לגיל:_ {session['age_notes']['space']}\n\n"

    text += "💡 בהצלחה! זכור: המטרה היא שהם **יחשבו**, לא רק יבצעו."
    return text


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("בוטל.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def main():
    init_db()
    if not BOT_TOKEN or BOT_TOKEN == "הכנס_כאן_את_הטוקן_שלך":
        print("שגיאה: חסר BOT_TOKEN. הגדר משתנה סביבה או הכנס טוקן בקוד.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^(new_weekly|age_|sess_)")],
        states={
            CHOOSING_AGE: [CallbackQueryHandler(button_handler, pattern="^age_")],
            CHOOSING_SESSIONS: [CallbackQueryHandler(button_handler, pattern="^sess_")],
            ENTERING_FOCUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_focus)],
            ENTERING_SECONDARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_secondary)],
            CONFIRMING: [CallbackQueryHandler(button_handler, pattern="^(confirm_plan|main_menu)")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("הבוט עולה...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

