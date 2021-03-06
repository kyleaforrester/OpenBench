# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#                                                                             #
#   OpenBench is a chess engine testing framework authored by Andrew Grant.   #
#   <https://github.com/AndyGrant/OpenBench>           <andrew@grantnet.us>   #
#                                                                             #
#   OpenBench is free software: you can redistribute it and/or modify         #
#   it under the terms of the GNU General Public License as published by      #
#   the Free Software Foundation, either version 3 of the License, or         #
#   (at your option) any later version.                                       #
#                                                                             #
#   OpenBench is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of            #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the             #
#   GNU General Public License for more details.                              #
#                                                                             #
#   You should have received a copy of the GNU General Public License         #
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.     #
#                                                                             #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

from __future__ import print_function

import argparse, ast, hashlib, json, math, multiprocessing, os
import platform, re, requests, shutil, subprocess, sys, time, zipfile


HTTP_TIMEOUT          = 30  # Timeout in seconds for requests
WORKLOAD_TIMEOUT      = 60  # Timeout when there is no work
ERROR_TIMEOUT         = 60  # Timeout when an error is thrown
GAMES_PER_CONCURRENCY = 32  # Total games to play per concurrency

CUSTOM_SETTINGS = {
    'ETHEREAL'  : { 'args' : [] }, # Configuration for Ethereal
    'LASER'     : { 'args' : [] }, # Configuration for Laser
    'WEISS'     : { 'args' : [] }, # Configuration for Weiss
    'DEMOLITO'  : { 'args' : [] }, # Configuration for Demolito
    'RUBICHESS' : { 'args' : [] }, # Configuration for RubiChess
};


# Treat Windows and Linux systems differently
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX   = platform.system() != 'Windows'


def pathjoin(*args):

    # Join a set of URL paths while maintaining the correct
    # format of "/"'s between each part of the URL's pathway

    args = [f.lstrip("/").rstrip("/") for f in args]
    return "/".join(args) + "/"

def killCutechess(cutechess):

    try:
        # Manually kill process trees for Windows
        if IS_WINDOWS:
            subprocess.call(['taskkill', '/F', '/T', '/PID', str(cutechess.pid)])
            cutechess.wait()
            cutechess.stdout.close()

        # Subprocesses close nicely on Linux
        if IS_LINUX:
            cutechess.kill()
            cutechess.wait()
            cutechess.stdout.close()

    except Exception as error:
        return

def getFile(source, output):

    # Download the source file
    print('Downloading {0}'.format(source))
    request = requests.get(url=source, stream=True, timeout=HTTP_TIMEOUT)

    # Write the file out chunk by chunk
    with open(output, 'wb') as fout:
        for chunk in request.iter_content(chunk_size=1024):
            if chunk: fout.write(chunk)
        fout.flush()

def getAndUnzipFile(source, name, output):

    # Download and extract .zip file
    getFile(source, name)
    with zipfile.ZipFile(name) as fin:
        fin.extractall(output)

    # Cleanup by deleting the .zip
    os.remove(name)

def getCutechess(server):

    # Ask the server where the core files are saved
    source = requests.get(
        pathjoin(server, 'getFiles'),
        timeout=HTTP_TIMEOUT).content.decode('utf-8')

    # Windows workers need the cutechess.exe and the Qt5Core dll.
    # Linux workers need cutechess and the libcutechess SO.
    # Make sure Linux binaries are set to be executable.

    if IS_WINDOWS and not os.path.isfile('cutechess.exe'):
        getFile(pathjoin(source, 'cutechess-windows.exe'), 'cutechess.exe')

    if IS_WINDOWS and not os.path.isfile('Qt5Core.dll'):
        getFile(pathjoin(source, 'cutechess-qt5core.dll'), 'Qt5Core.dll')

    if IS_LINUX and not os.path.isfile('cutechess'):
        getFile(pathjoin(source, 'cutechess-linux'), 'cutechess')
        os.system('chmod 777 cutechess')

    if IS_LINUX and not os.path.isfile('libcutechess.so.1'):
        getFile(pathjoin(source, 'libcutechess.so.1'), 'libcutechess.so.1')

def getMachineID():

    # Check if the machine is registered
    if os.path.isfile('machine.txt'):
        with open('machine.txt', 'r') as fin:
            return fin.readlines()[0]

    # Notify user when the machine is new
    print('[NOTE] Machine Is Unregistered')
    return 'None'

def getEngine(data, engine):

    # Log the fact that we are setting up a new engine
    print('Engine {0}'.format(data['test']['engine']))
    print('Branch {0}'.format(engine['name']))
    print('Commit {0}'.format(engine['sha']))
    print('Source {0}'.format(engine['source']))

    # Extract the zipfile to /tmp/ for future processing
    # Format: https://github.com/User/Engine/archive/SHA.zip
    tokens = engine['source'].split('/')
    unzipname = '{0}-{1}'.format(tokens[-3], tokens[-1].replace('.zip', ''))
    getAndUnzipFile(engine['source'], '{0}.zip'.format(engine['name']), 'tmp')
    pathway = pathjoin('tmp/{0}/'.format(unzipname), data['test']['path'])

    # Check CUSTOM_SETTINGS for a custom configuration
    command = ['make', 'EXE={0}'.format(engine['name'])]
    if data['test']['engine'].upper() in CUSTOM_SETTINGS:
        config = CUSTOM_SETTINGS[data['test']['engine'].upper()]
        command.extend(config['args'])

    # Build the engine. If something goes wrong with the
    # compilation process, we will figure this out later on
    subprocess.Popen(command, cwd=pathway).wait()
    print("") # Leave a new line to seperate output

    # Move the binary to the /Engines/ directory
    output = '{0}{1}'.format(pathway, engine['name'])
    destination = 'Engines/{0}'.format(engine['sha'])

    # Check to see if the compiler included a file extension or not
    if os.path.isfile(output): os.rename(output, destination)
    if os.path.isfile(output + '.exe'): os.rename(output + '.exe', destination)

    # Cleanup the zipfile directory
    shutil.rmtree('tmp')

def getCutechessCommand(arguments, data, nps):

    # Parse options for Dev
    tokens = data['test']['dev']['options'].split(' ')
    devthreads = int(tokens[0].split('=')[1])
    devoptions = ' option.'.join(['']+tokens)

    # Parse options for Base
    tokens = data['test']['base']['options'].split(' ')
    basethreads = int(tokens[0].split('=')[1])
    baseoptions = ' option.'.join(['']+tokens)

    # Scale the time control for this machine's speed
    timecontrol = computeAdjustedTimecontrol(arguments, data, nps)

    # Find max concurrency for the given testing conditions
    concurrency = int(math.floor(int(arguments.threads) / max(devthreads, basethreads)))

    # Check for an FRC/Chess960 opening book
    if "FRC" in data['test']['book']['name'].upper(): variant = 'fischerandom'
    elif "960" in data['test']['book']['name'].upper(): variant = 'fischerandom'
    else: variant = 'standard'

    # General Cutechess options
    generalflags = '-repeat -recover -srand {0} -resign {1} -draw {2} -wait 10'.format(
        int(time.time()), 'movecount=3 score=400', 'movenumber=40 movecount=8 score=10'
    )

    # Options about tournament conditions
    setupflags = '-variant {0} -concurrency {1} -games {2}'.format(
        variant, concurrency, concurrency * GAMES_PER_CONCURRENCY
    )

    # Options for the Dev Engine
    devflags = '-engine cmd=./Engines/{0} proto={1} tc={2}{3} name={4}'.format(
        data['test']['dev']['sha'], data['test']['dev']['protocol'], timecontrol,
        devoptions, '{0}-{1}'.format(data['test']['engine'], data['test']['dev']['sha'][:8])
    )

    # Options for the Base Engine
    baseflags = '-engine cmd=./Engines/{0} proto={1} tc={2}{3} name={4}'.format(
        data['test']['base']['sha'], data['test']['base']['protocol'], timecontrol,
        baseoptions, '{0}-{1}'.format(data['test']['engine'], data['test']['base']['sha'][:8])
    )

    # Options for opening selection
    bookflags = '-openings file={0} format={1} order=random plies=16'.format(
        data['test']['book']['name'], data['test']['book']['name'].split('.')[-1]
    )

    # Combine all flags and add the cutechess program callout
    options = ' '.join([generalflags, setupflags, devflags, baseflags, bookflags])
    if IS_WINDOWS: return 'cutechess.exe {0}'.format(options), concurrency
    if IS_LINUX: return './cutechess {0}'.format(options), concurrency


def parseStreamOutput(output):

    # None unless found
    bench = None; speed = None

    # Split the output line by line and look backwards
    for line in output.decode('ascii').strip().split('\n')[::-1]:

        # Convert all non-alpha numerics to spaces
        line = re.sub(r'[^a-zA-Z0-9 ]+', ' ', line)

        # Search for node or speed counters
        bench1 = re.search(r'[0-9]+ NODES', line.upper())
        bench2 = re.search(r'NODES[ ]+[0-9]+', line.upper())
        speed1 = re.search(r'[0-9]+ NPS'  , line.upper())
        speed2 = re.search(r'NPS[ ]+[0-9]+'  , line.upper())

        # A line with no parsable information was found
        if not bench1 and not bench2 and not speed1 and not speed2:
            break

        # A Bench value was found
        if not bench and (bench1 or bench2):
            bench = bench1.group() if bench1 else bench2.group()

        # A Speed value was found
        if not speed and (speed1 or speed2):
            speed = speed1.group() if speed1 else speed2.group()

    # Parse out the integer portion from our matches
    bench = int(re.search(r'[0-9]+', bench).group()) if bench else None
    speed = int(re.search(r'[0-9]+', speed).group()) if speed else None
    return (bench, speed)

def computeSingleThreadedBenchmark(engine, outqueue):

    try:
        # Launch the engine and run a benchmark
        dir = os.path.join('Engines', engine)
        stdout, stderr = subprocess.Popen(
            './{0} bench'.format(dir).split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).communicate()

        # Parse output streams for the benchmark data
        bench, speed = parseStreamOutput(stdout)
        if bench is None or speed is None:
            bench, speed = parseStreamOutput(stderr)
        outqueue.put((int(bench), int(speed)))

    # Missing file, unable to run, failed to compile, or some other
    # error. Force an exit by sending back a null bench and nps value
    except Exception as error:
        print("[ERROR] {0}".format(str(error)))
        outqueue.put((0, 0))

def computeMultiThreadedBenchmark(arguments, engine):

    # Log number of benchmarks being spawned for the given engine
    print('Running {0}x Benchmarks for {1}'.format(arguments.threads, engine['name']))

    # Each computeSingleThreadedBenchmark() reports to this Queue
    outqueue = multiprocessing.Queue()

    # Spawn a computeSingleThreadedBenchmark() for each thread
    processes = [
        multiprocessing.Process(
            target=computeSingleThreadedBenchmark,
            args=(engine['sha'], outqueue,)
        ) for f in range(int(arguments.threads))
    ]

    # Launch every benchmark
    for process in processes:
        process.start()

    # Wait for each benchmark
    for process in processes:
        process.join()

    # Extract the benches and nps counts from each worker
    data  = [outqueue.get() for f in range(int(arguments.threads))]
    bench = [int(f[0]) for f in data]
    speed = [int(f[1]) for f in data]
    avg   = sum(speed) / len(speed)

    # Flag an error if there were different benches
    if (len(set(bench)) > 1): return (0, 0)

    # Log and return computed bench and speed
    print ('Bench for {0} is {1}'.format(engine['name'], bench[0]))
    print ('speed for {0} is {1}\n'.format(engine['name'], int(avg)))
    return (bench[0], avg)

def computeAdjustedTimecontrol(arguments, data, nps):

    # Scale and report the nodes per second
    factor = int(data['test']['nps']) / nps
    timecontrol = data['test']['timecontrol'];
    reportNodesPerSecond(arguments, data, nps)

    # Parse X / Y + Z time controls
    if '/' in timecontrol and '+' in timecontrol:
        moves = timecontrol.split('/')[0]
        start, inc = map(float, timecontrol.split('/')[1].split('+'))
        start = round(start * factor, 2)
        inc = round(inc * factor, 2)
        return moves + '/' + str(start) + '+' + str(inc)

    # Parse X / Y time controls
    elif '/' in timecontrol:
        moves = timecontrol.split('/')[0]
        start = float(timecontrol.split('/')[1])
        start = round(start * factor, 2)
        return moves + '/' + str(start)

    # Parse X + Z time controls
    else:
        start, inc = map(float, timecontrol.split('+'))
        start = round(start * factor, 2)
        inc = round(inc * factor, 2)
        return str(start) + '+' + str(inc)


def verifyOpeningBook(data):

    # Fetch the opening book if we don't have it
    print('\nFetching and Verifying Opening Book')
    if not os.path.isfile(data['name']):
        source = '{0}.zip'.format(data['source'])
        name = '{0}.zip'.format(data['name'])
        getAndUnzipFile(source, name, '')

    # Verify data integrity with a hash
    with open(data['name']) as fin:
        content = fin.read().encode('utf-8')
        sha = hashlib.sha256(content).hexdigest()

    # Log the SHA verification
    print('Correct SHA {0}'.format(data['sha']))
    print('Download SHA {0}\n'.format(sha))

    # Signal for error when SHAs do not match
    return data['sha'] == sha

def verifyEngine(arguments, data, engine):

    # Download the engine if we do not already have it
    if not os.path.isfile('Engines/{0}'.format(engine['sha'])):
        getEngine(data, engine)

    # Run a group of benchmarks in parallel in order to better scale NPS
    # values for this worker. We obtain a bench and average NPS value
    bench, nps = computeMultiThreadedBenchmark(arguments, engine)

    # Check for an invalid bench. Signal to the Client and the Server
    if bench != int(engine['bench']):
        reportWrongBenchmark(arguments, data, engine)
        print ('[ERROR] Invalid Bench. Got {0} Expected {1}'.format(bench, engine['bench']))

    # Return a valid bench or otherwise return None
    return nps if bench == int(engine['bench']) else None


def reportWrongBenchmark(arguments, data, engine):

    # Server wants user verification, and then information about
    # the test that threw the error, and which engine did it
    data = {
        'username' : arguments.username,
        'password' : arguments.password,
        'testid'   : data['test']['id'],
        'engineid' : engine['id'],
    }

    # Hit the server with information about wrong benchmark
    url = pathjoin(arguments.server, 'wrongBench')
    return requests.post(url, data=data, timeout=HTTP_TIMEOUT).text

def reportNodesPerSecond(arguments, data, nps):

    # Server wants user verification, and then information about
    # nodes per second searched for a specific machine id value
    data = {
        'username'  : arguments.username,
        'password'  : arguments.password,
        'machineid' : data['machine']['id'],
        'nps'       : nps,
    }

    # Hit the server with information about nps
    url = pathjoin(arguments.server, 'submitNPS')
    return requests.post(url, data=data, timeout=HTTP_TIMEOUT).text

def reportResults(arguments, data, wins, losses, draws, crashes, timelosses):

    # Server wants user verification, and then information about the machine,
    # the result object, the test, and then the actual updated game results
    data = {
        'username'  : arguments.username,    'wins'      : wins,
        'password'  : arguments.password,    'losses'    : losses,
        'machineid' : data['machine']['id'], 'draws'     : draws,
        'resultid'  : data['result']['id'],  'crashes'   : crashes,
        'testid'    : data['test']['id'],    'timeloss'  : timelosses,
    }

    # Hit the server with the updated test results
    url = pathjoin(arguments.server, 'submitResults')
    try: return requests.post(url, data=data, timeout=HTTP_TIMEOUT).text
    except: print('[NOTE] Unable To Reach Server'); return "Unable"


def processCutechess(arguments, data, cutechess, concurrency):

    # Tracking for game results
    crashes = timelosses = 0
    score = [0, 0, 0]; sent = [0, 0, 0]

    while True:

        # Output the next line or quit when the pipe closes
        line = cutechess.stdout.readline().strip().decode('ascii')
        if line != '': print(line)
        else: cutechess.wait(); return

        # Parse engine crashes
        if 'disconnects' in line or 'connection stalls' in line:
            crashes += 1

        # Parse losses on time
        if 'on time' in line:
            timelosses += 1

        # Parse updates to scores
        if line.startswith('Score of'):

            # Format: Score of test vs base: W - L - D  [0.XXX] N
            score = list(map(int, line.split(':')[1].split()[0:5:2]))

            # After every `concurrency` results, update the server
            if (sum(score) - sum(sent)) % concurrency == 0:

                # Look only at the delta since last report
                WLD = [score[f] - sent[f] for f in range(3)]
                status = reportResults(arguments, data, *WLD, crashes, timelosses)

                # Check for the task being aborted
                if status.upper() == 'STOP':
                    killCutechess(cutechess)
                    return

                # If we fail to update the server, hold onto the results
                if status.upper() != 'UNABLE':
                    crashes = timelosses = 0
                    sent = score[::]

def processWorkload(arguments, data):

    # Verify and possibly download the opening book
    if not verifyOpeningBook(data['test']['book']):
        sys.exit()

    # Download, Verify, and Benchmark each engine. If we are unable
    # to obtain a valid bench for an engine, we exit this workload
    devnps = verifyEngine(arguments, data, data['test']['dev'])
    basenps = verifyEngine(arguments, data, data['test']['base'])

    avgnps = (devnps + basenps) / 2
    command, concurrency = getCutechessCommand(arguments, data, avgnps)
    print("Launching Cutechess\n{0}\n".format(command))

    cutechess = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
    processCutechess(arguments, data, cutechess, concurrency)

def completeWorkload(workRequestData, arguments):

    # Get the next workload
    data = requests.post(
        pathjoin(arguments.server, 'getWorkload'),
        data=workRequestData, timeout=HTTP_TIMEOUT).content.decode('utf-8')

    # Check for an empty workload
    if data == 'None':
        print('[NOTE] Server Has No Work')
        time.sleep(WORKLOAD_TIMEOUT)
        return

    # Kill process if unable to login
    if data == 'Bad Credentials':
        print('[ERROR] Invalid Login Credentials')
        sys.exit()


    # Bad machines will be registered again
    if data == 'Bad Machine':
        workRequestData['machineid'] = 'None'
        print('[NOTE] Invalid Machine ID')
        return

    # Convert response into a dictionary
    data = ast.literal_eval(data)

    # Update machine ID in case we got registered
    if workRequestData['machineid'] != data['machine']['id']:
        workRequestData['machineid'] = data['machine']['id']
        with open('machine.txt', 'w') as fout:
            fout.write(str(workRequestData['machineid']))

    # Handle the actual workload's completion
    processWorkload(arguments, data)


def main():

    # Use OpenBench.py's path as the base pathway
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Expect a Username, Password, Server, and Threads value
    p = argparse.ArgumentParser()
    p.add_argument('-U', '--username', help='Username', required=True)
    p.add_argument('-P', '--password', help='Password', required=True)
    p.add_argument('-S', '--server', help='Server Address', required=True)
    p.add_argument('-T', '--threads', help='Number of Threads', required=True)
    arguments = p.parse_args()

    # All workload requests must be tied to a user and a machine.
    # We also pass a thread count to inform the server what tests this
    # machine can handle. We pass the osname in order to register machines
    workRequestData = {
        'machineid' : getMachineID(),
        'username'  : arguments.username,
        'password'  : arguments.password,
        'threads'   : arguments.threads,
        'osname'    : '{0} {1}'.format(platform.system(), platform.release())
    };

    # Make sure we have cutechess installed
    getCutechess(arguments.server)

    # Create the Engines directory if it does not exist
    if not os.path.isdir('Engines'):
        os.mkdir('Engines')

    # Continually pull down and complete workloads
    while True:
        try: completeWorkload(workRequestData, arguments)
        except Exception as error:
            print ('[ERROR] {0}'.format(str(error)))
            time.sleep(ERROR_TIMEOUT)

if __name__ == '__main__':
    main()
