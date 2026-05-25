# Municipality Biking Safety Risk Analysis

This project analyzes municipal safety trends and risk profiles in Flanders.

## Setup Instructions

To run this project, please follow these steps to set up your environment:

### 1. Clone the repository
```bash
git clone https://github.com/aradmehralian/Modern-Data-Analytics-Project.git
cd Modern-Data-Analytics-Project

## Windows Bash
python -m venv venv
venv\Scripts\activate

## MacOS/Linux

python3 -m venv venv
source venv/bin/activate

##dependencies

pip install -r requirements.txt

##opening notebooks

jupyter notebook

#for the data requirements, the curated and ext files which are used in the EDA notebook have been provided as zipped files 
#since the raw aggregated file was too big it has been hosted on GDrive with instruction to download provided in the DATA.MD file
#once that is downloaded and everything is unzipped into the folders they are named as, the EDA notebook should work as expected
#if you wish to just go through, the raw files are not necessary since the notebook also has steps to just read the processed files so you may continue from there