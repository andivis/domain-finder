# domain-finder

## Video

https://www.loom.com/share/4f43f11ce7e9405cb165874ac305e154

## Installation

1. Make sure Python 3.6 or higher, pip and git are installed. For example, on Ubuntu run the commands below in a terminal.

```
sudo apt install -y python3
sudo apt install -y python3-pip
sudo apt install -y git
```

2. Open a terminal window
3. Run the commands below. Depending on your system you may need run `pip3` instead of `pip`.

```
git clone https://github.com/andivis/domain-finder.git
cd domain-finder
pip install lxml
```

## Instructions

1. Open a terminal window. Cd to the directory containing `main.py`. It's where you cloned the repository before.
2. Optionally, edit the `options.ini` file to your liking
3. Optionally, put your proxy list into `proxies.csv`. The header must contain `url,port,username,password`. The other lines follow that format.
4. Make sure `input.csv` contains the company information.
5. Run `python main.py`. Depending on your system you may need run `python3 main.py` instead.
6. You can multiple instances at the same time. On Linux/MacOs run `bash run.sh`. On Windows, run `run.bat`. That will divide the work up among multiple processes and therefore finish much faster

## Command line parameters

- `-threadNumber`: . Default: `1`.
- `-threadCount`: how many threads to run. Default: `1`.
- `--combine`: if present the script just combines the output from the other threads and writes it to `output.csv`