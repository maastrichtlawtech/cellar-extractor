import glob
import argparse
import logging
from pathlib import Path
from cellar_extractor.json_to_csv import read_csv
from cellar_extractor.persistence import write_dataframe_csv


def extract_rows(data, number):
    """
    Method takes in a dataframe and returns a dataframe
    with only *number* of data rows.
    """

    try:
        output = data[1:number]
    except Exception:
        logging.info(
            f"The file does not have {number} entries,\
                     returning entire file."
        )
        output = data
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--amount", help="number of rows to extract", type=int, required=True
    )
    parser.add_argument(
        "--input-dir",
        help="directory containing CSV files to trim",
        default=".",
    )
    parser.add_argument(
        "--output-dir",
        help="directory where trimmed CSV files will be written",
        required=True,
    )
    args = parser.parse_args()
    number = args.amount
    print("")
    print("EXTRACTION FROM CSV FILE IN DATA PROCESSED DIR STARTED")
    print("")
    csv_files = glob.glob(args.input_dir + "/" + "*.csv")
    print(f"FOUND {len(csv_files)} CSV FILES")

    for i in range(len(csv_files)):
        # Approach for manual extraction of a specific file in a
        # specific directory
        if "clean" not in csv_files[i]:
            print("")
            print(f"EXTRACTING FROM {csv_files[i]} ")
            data = read_csv(csv_files[i])
            output = extract_rows(data, number)
            filename = Path(csv_files[i]).name
            output_path = str(Path(args.output_dir) / filename)
            write_dataframe_csv(output, output_path)
    print("")
    print("Extraction DONE")
    print("")
