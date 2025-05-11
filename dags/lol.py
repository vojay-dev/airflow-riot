import asyncio
import json
import os
from datetime import datetime

from airflow.sdk import dag, task, Variable
from airflow.timetables.trigger import MultipleCronTriggerTimetable

from dags.riot import RiotApiClient, Summoner, Match

API_KEY = Variable.get("riot_api_key")

@dag(
    schedule=MultipleCronTriggerTimetable(
        "0 10 * * *",
        "0 14 * * *",
        timezone="UTC"
    ),
    start_date=datetime(2025, 5, 10),
    dag_display_name="League of Legends 🎮 - Champion Performance Analysis 🏆"
)
def lol():

    @task
    def fetch_top_players():
        client = RiotApiClient(API_KEY)
        players = asyncio.run(client.get_top_players())

        # Convert Pydantic models to dictionaries for Airflow compatible serialization
        return [player.model_dump(by_alias=True) for player in players]

    @task
    def fetch_matches(summoner):
        # Convert dictionaries back to Pydantic models
        summoner = Summoner.model_validate(summoner)

        client = RiotApiClient(API_KEY)
        matches = asyncio.run(client.get_matches_for_summoners([summoner], matches_per_summoner=5))

        return [match.model_dump(by_alias=True) for match in matches]

    @task
    def combine_matches(match_lists):
        all_matches = [Match.model_validate(match) for sublist in match_lists for match in sublist]
        unique_matches = []

        for match in all_matches:
            if match not in unique_matches:
                unique_matches.append(match)

        return [match.model_dump(by_alias=True) for match in unique_matches]

    @task.llm(model="gemini-2.0-flash", result_type=str, system_prompt="""
    You are a professional League of Legends analyst. Your task is to analyze the provided match data and generate a\
    visually appealing HTML report summarizing champion performance.

    The HTML report should include:
    1.  A main title for the report (e.g., "League of Legends - Champion Performance Analysis").
    2.  Sections for each champion tier: S, A, B, C, D (best to worst).
    3.  Within each tier section:
        *   A clear heading for the tier (e.g., "S Tier Champions").
        *   A list or cards for each champion in that tier.
        *   For each champion, display:
            *   Their name.
            *   A small image of the champion. Try to use image URLs from Riot's Data Dragon CDN. For example: `http://ddragon.leagueoflegends.com/cdn/{{LATEST_PATCH}}/img/champion/{{ChampionNameKey}}.png`. (e.g., `Aatrox.png`, `MonkeyKing.png` for Wukong). If you are unsure of the exact champion name key or latest patch, make a best guess or use a generic placeholder image URL if necessary.
            *   Key performance statistics (e.g., Win Rate, KDA, Games Played from the data).
            *   A concise justification for their tier placement.
    4.  Apply basic inline CSS or a `<style>` block for a clean, professional, and visually appealing layout. Consider:
        *   A readable font family.
        *   Distinct visual styles for different tiers (e.g., background colors for tier sections or champion cards).
        *   Good spacing and alignment.
        *   Making champion images a reasonable size (e.g., 50x50 pixels).
    5.  The final output MUST be a single, valid HTML string, starting with `<!DOCTYPE html>` and ending with `</html>`.
    """)
    def analyze(unique_matches):
        return json.dumps(unique_matches, default=str)

    @task
    def send_report(report):
        created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.realpath(os.path.dirname(__file__))
        report_path = f"{base_dir}/lol_ai_champion_report_{created_at}.html"

        with open(report_path, "w") as f:
            f.write(f"*Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
            f.write(report)

        print(f"Report written to {report_path}")
        print("::group::Generated report")
        print(report)
        print("::endgroup::")

    top_players = fetch_top_players()
    matches = fetch_matches.expand(summoner=top_players)
    unique_matches = combine_matches(matches)
    report = analyze(unique_matches)
    send_report(report)

lol()
