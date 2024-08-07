import os
import requests
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from db_utils import insert_rows, make_db_connection, select_all_from_col

def video_ids_api_request(video_ids, api_key, collected_at):
    # get information about videos given video_ids
    videos_api_url = "https://www.googleapis.com/youtube/v3/videos"

    video_df = pd.DataFrame(columns=["collected_at", 
                                 "video_id", 
                                 "publish_datetime", 
                                 "channel_id",
                                 "video_title",
                                 "video_description",
                                 "channel_title",
                                 "num_tags", 
                                 "category_id",  
                                 "duration", 
                                 "licensed_content", 
                                 "made_for_kids", 
                                 "num_views", 
                                 "num_likes", 
                                 "num_comments"])
    
    # API limits 50 videos per call with no pages
    # split videos into chunks of 50
    videos_chunked = make_chunks(video_ids, 50)

    for videos in videos_chunked:
        params = {
            "key": api_key,
            "part": "id, snippet, contentDetails, status, statistics",
            "id": ",".join(videos),
            "hl": "en",
            "regionCode": "US",
            "maxResults": 50,
        }

        response = requests.get(videos_api_url, params=params)

        if response.status_code == 200:
            response_json = response.json()

            for video in response_json["items"]:
                # add video details and datetime of request to end of video dataframe
                video_df.loc[len(video_df)] = [collected_at] + parse_video_json(video)

        else:
            print(f"response.status_code = {response.status_code}")

    return video_df

def parse_video_json(video):

    video_id = video["id"]

    # snippet
    publish_datetime = video["snippet"]["publishedAt"]
    channel_id = video["snippet"]["channelId"]
    video_title = video["snippet"]["title"]
    video_description = video["snippet"]["description"]
    channel_title = video["snippet"]["channelTitle"]
    num_tags = len(video["snippet"].get("tags", [])) # can be null
    category_id = video["snippet"]["categoryId"]

    # contentDetails
    duration = video["contentDetails"]["duration"]
    licensed_content = video["contentDetails"]["licensedContent"]

    # status
    made_for_kids = video["status"]["madeForKids"]

    # statistics
    num_views = video["statistics"]["viewCount"]
    num_likes = video["statistics"].get("likeCount", None) # can be null
    num_comments = video["statistics"].get("commentCount", None) # can be null

    return [video_id, 
            publish_datetime, 
            channel_id, 
            video_title,
            video_description,
            channel_title,
            num_tags,
            category_id, 
            duration, 
            licensed_content, 
            made_for_kids, 
            num_views, 
            num_likes, 
            num_comments]   

def make_chunks(lst, n):
    # https://stackoverflow.com/questions/312443/how-do-i-split-a-list-into-equally-sized-chunks
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def main():
    collected_at = datetime.now(timezone.utc) # YT API uses UTC timezone
    
    # Load environment variables from .env file
    load_dotenv("environment_variables.env")
    api_key = os.getenv("API_KEY")
    psql_pw = os.getenv("PSQL_PW")

    # Connect to AWS RDS through SSH tunnel
    conn, cursor, tunnel = make_db_connection(psql_pw)

    # Videos ETL
    # EXTRACT
    # get all video_ids in video_dim table
    video_ids = select_all_from_col("video_id", "video_dim", cursor)

    # make api request to get current info for all the videos
    video_df = video_ids_api_request(video_ids, api_key, collected_at)

    # TRANSFORM
    # turn publish_datetime into datetime dtype
    video_df["publish_datetime"] = pd.to_datetime(video_df["publish_datetime"])
    video_df.rename(columns={"publish_datetime": "published_at"}, inplace=True)

    # parse duration into seconds
    video_df["duration"] = pd.to_timedelta(video_df["duration"]).apply(lambda x: x.seconds)
    video_df.rename(columns={"duration": "duration_seconds"}, inplace=True)

    # fill nulls
    video_df[["num_views", "num_likes", "num_comments"]] = video_df[["num_views", "num_likes", "num_comments"]].fillna(0)
    
    # turn to int
    video_df[["num_views", "num_likes", "num_comments"]] = video_df[["num_views", "num_likes", "num_comments"]].astype(dtype=int)

    # LOAD
    # insert into fact table
    insert_rows(video_df, 
                ["collected_at", "video_id", "num_views", "num_likes", "num_comments"], 
                "video_fact", 
                cursor, 
                conn)

    conn.close()
    cursor.close()
    tunnel.stop()

if __name__ == "__main__":
    main()