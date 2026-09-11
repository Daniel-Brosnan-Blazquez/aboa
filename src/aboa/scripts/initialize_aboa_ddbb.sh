#!/bin/bash
# Initialize ABOA DDBB, retrying until PostgreSQL is ready.
echo
echo "####################"
echo "Initialize ABOA DDBB"
echo "####################"
while true
do
    echo "Trying to initialize ABOA database..."
    aboa_init.py -y
    status=$?
    if [ $status -ne 0 ]
    then
        echo "Server is not ready yet..."
        sleep 1
    else
        echo "Database has been initialized... :-)"
        break
    fi
done
