#! /bin/bash

cd /etc/runonce.d
for file in *
do
    if [ ! -f "$file" ]
    then
        continue
    fi
    "./$file"
    mv "$file" "/etc/runonce.d/ran/$file.$(date +%Y%m%dT%H%M%S)"
    logger -t runonce -p local3.info "$file"
done

