from pyrosm import get_data

fp = get_data("Moscow", directory="/home/xgb/projects/rollermap/data")
print("Data was downloaded to:", fp)