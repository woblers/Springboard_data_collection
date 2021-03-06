#!/usr/bin/python

import pandas as pd
from dateutil import parser
import datetime
import requests
from bs4 import BeautifulSoup


# Custom error
class SpringboardError(Exception):
    pass


def read_data(file_path):
    
    """Reads in the existing data stored at a CSV at the supplied filepath.
    
    The CSV must be in the format:
    
        -----------------------------------------------------
        | Date (index)  |  Camera Name 1  |  Camera Name 2  | etc.
        -----------------------------------------------------
        |   27-07-2017  |  345            |  672            |
        |   28-07-2017  |  421            |  554            | 
        |   29-07-2017  |  513            |  786            |
        
        etc.
        
    """
    
    df = pd.read_csv(file_path, index_col = 0)

    # Make sure the index is proper DateTime
    df.index = pd.to_datetime(df.index, dayfirst = True)
    
    return df

def get_new_data(user, password, 
                 from_datetime = datetime.datetime(1997,1,1),
                 to_datetime = datetime.datetime(2097,1,1)):
    
    """Makes the GET request to the Springboard API using the arguments supplied.
    
    The hourly data returned by the API request is then aggregated to the daily 
    level per camera, returning a dataframe with the following format:
    
        -----------------------------------------------------
        | Date (index)  |  Camera Name 1  |  Camera Name 2  | etc.
        -----------------------------------------------------
        |   30-07-2017  |  345            |  672            |
        |   30-07-2017  |  421            |  554            | 
        |   01-08-2017  |  513            |  786            |
        
        etc.
        
    """
    
    url = "https://performv4.spring-board.info/outputs/footfalloutput.aspx?useremail={}\
    &userpassword={}\
    &startdate={}\
    &enddate={}\
    &changestartdate=19970101&changeenddate=20970101"\
    .format(user, password, from_datetime.strftime("%Y%m%d"), to_datetime.strftime("%Y%m%d"))
        
    # Make the request to get the full html page
    get_request = requests.get(url)
    print("Collecting data from Springboard:\n > From: {}\n > To: {}\n"\
          .format(from_datetime.strftime("%d %B %Y"), to_datetime.strftime("%d %B %Y")))

    # Use BeasutifulSoup to parse the HTML
    html_doc = get_request.text
    soup = BeautifulSoup(html_doc, "html.parser")

    # Extract the data from the HTML table.
    data = []
    table = soup.find("table")

    # Check if the API request returned data.
    # Can't use the status code for this because it returns status 200
    # even if garbage credentials are used for the request.
    if len(table) == 3:
        raise SpringboardError("No data returned by API; check credentials.")

    elif len(table) > 3:
        rows = table.find_all("tr")
        for r in rows:
            cols = r.find_all("td")
            cols = [ele.text.strip() for ele in cols]
            data.append([ele for ele in cols if ele])

        # Convert to a pandas dataframe
        new_data = pd.DataFrame(data[1:], columns = data[0])

        # Check the API request has returned the required columns, raise an error if not.
        required_columns = ["InCount", "OutCount"]
        for column in required_columns:
            if column not in new_data.columns:
                raise SpringboardError("Required columns not returned by the API request.")
            else:
                # If the columns are present, convert them to numeric.
                new_data[column] = pd.to_numeric(new_data[column])

        # Add in a FootfallDateTime column
        new_data["FootfallDateTime"] = [parser.parse(new_data.loc[row,"FootfallDate"] + " "\
                                                               + new_data.loc[row,"FootfallTime"]) \
                                         for row in range(len(new_data))]

        # Add in DayTotal columns to sum all footfall for the day per location
        new_data["InDayTotal"] = new_data.groupby(["LocationName","FootfallDate"])["InCount"].transform("sum")
        new_data["OutDayTotal"] = new_data.groupby(["LocationName","FootfallDate"])["OutCount"].transform("sum")

        # Add InOutMax column
        new_data["InOutMax"] = new_data[["InDayTotal","OutDayTotal"]].max(axis=1)

        # Group the data by date & location
        grouped_df = new_data.groupby(["FootfallDate", "LocationName"])["InOutMax"]\
        .aggregate("first").unstack().fillna(0).astype("int")

        # Reset the index to the Date column
        grouped_df.reset_index(level = 0, inplace = True)
        grouped_df.rename(columns={"FootfallDate":"Date"}, inplace = True)
        grouped_df["Date"] = pd.to_datetime(grouped_df["Date"], dayfirst = True)
        grouped_df.set_index("Date", inplace = True)

        # Sort by the new Date index
        grouped_df.sort_index(inplace=True)
        
    return grouped_df


def Springboard_data(useremail, userpassword,
                     new_data_filepath,
                     primary_camera_name,
                     backup_data_filepath = None):
    
    # Read in the old data if it exists, else create new df.
    try:
        ff_to_date = read_data(new_data_filepath)
        
        # Latest date with data
        latest_date = max(ff_to_date[ff_to_date[primary_camera_name].notnull()].index)
        
        # First date with data
        first_date = min(ff_to_date[ff_to_date[primary_camera_name].notnull()].index)
        
        # Print message
        print("Latest data loaded:\n> From: {}".format(first_date.strftime("%d %B %Y")))
        print("> To: {} \n\nExisting data from:".format(latest_date.strftime("%d %B %Y")))
        cameras = ff_to_date.columns
        for camera in cameras:
            print("> {}".format(camera))
        print()
        
        # Backup the old data, if filepath supplied as argument.
        if backup_data_filepath:
            ff_to_date.to_csv(backup_data_filepath, index = True)
            print("Backing up old data:\n> From: {}".format(first_date.strftime("%d %B %Y")))
            print("> To: {} \nSuccess; old data backed up to:".format(latest_date.strftime("%d %B %Y")))
            print("> {}\n".format(backup_data_filepath))
        
        old_data_found = True
    
    except FileNotFoundError:
        ff_to_date = pd.DataFrame(index = ["Date"])
        old_data_found = False
    
    if old_data_found:
        # Day after most recent data we have.
        startdate = latest_date + datetime.timedelta(1)
    else:
        # Date a long time ago, to get all data to date.
        startdate = datetime(1997,1,1)    

    # Yesterday's date as the end date for the API request.
    yesterday = datetime.datetime.now() - datetime.timedelta(1)

    # If the data is up to date there is no need to query Springboard for fresh data.
    if (latest_date + datetime.timedelta(1)) <= yesterday:

        grouped_df = get_new_data(user = useremail, password = userpassword,
                                 from_datetime = startdate,
                                 to_datetime = yesterday)

        # Combine the old_data and new_data dataframes.
        frames = [ff_to_date, grouped_df]
        new_df = pd.concat(frames)

        # Save the new data
        new_df.to_csv(new_data_filepath, index = True)
        print("Saving new data:\n > From: {}\n > To: {} \n"\
              .format(first_date.strftime("%d %B %Y"), yesterday.strftime("%d %B %Y")))
        print("Success; new data saved to:\n> {}\n".format(new_data_filepath))

    else:
        print("Saved data at {} is already up to date.".format(new_data_filepath))