import os
import re
import csv
import pandas as pd

OUTPUT = './outputs/performance.csv'
COLLUME = 'time(ms)'


# Function to parse the file name
def parse_file_name(file_name):
    # Customize this regular expression to match the desired part of the file name
    pattern = r'_([\d.]+)_'
    match = re.search(pattern, file_name)
    if match:
        return match.group(1)
    return None


def process():
    # Specify the folder path
    folder_path = './temp'

    # Get a list of all the file names in the folder
    file_names = os.listdir(folder_path)

    # Parse the file names and store the parsed parts in a list
    parsed_parts = [parse_file_name(file_name) for file_name in file_names]

    # Create a CSV file and write the parsed parts to a column
    with open(OUTPUT, 'w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow([COLLUME])
        
        for parsed_part in parsed_parts:
            if parsed_part is not None:
                csv_writer.writerow([parsed_part])


def analysis():
    # Read the 'Parsed_Part' column from the CSV file
    data = []
    with open(OUTPUT, 'r') as csvfile:
        csv_reader = csv.reader(csvfile)
        next(csv_reader)  # Skip the header row
        for row in csv_reader:
            data.append(float(row[0]))  # Convert the data to float

    # Convert the list to a pandas DataFrame
    df = pd.DataFrame(data, columns=[COLLUME])
    df[COLLUME]


if __name__ == '__main__':
    process()
