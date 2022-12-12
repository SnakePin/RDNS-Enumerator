#!/usr/bin/env python3
from dns.resolver import NXDOMAIN, NoNameservers
from dns.asyncresolver import Resolver as AsyncResolver
from alive_progress import alive_bar
import asyncio
from json import dumps as json_dump
from ipaddress import IPv4Network
from argparse import ArgumentParser,BooleanOptionalAction
from random import uniform as rand_uniform
from socket import inet_aton

parser = ArgumentParser()
parser.add_argument('-t','--timeout', help='Timeout per request in seconds', default=5, type=float)
parser.add_argument('-r','--retries', help='Number of times to retry a DNS request in-case it fails', default=10, type=int)
parser.add_argument('-c','--concurrency', help='Number of requests to make in parallel', default=256, type=int)
parser.add_argument('-d','--dns-server', help='The DNS server to send the queries to', default='1.1.1.1', type=str)
parser.add_argument('-o','--out-file', help='The file to write the JSON output to', type=str)
parser.add_argument('-q', '--quiet', help='Disabled the progress bar on stdout',
        action=BooleanOptionalAction, default=False)
parser.add_argument("address", help="IP address or a CIDR range")
args = vars(parser.parse_args())

custom_resolver = AsyncResolver(configure=False)
custom_resolver.nameservers = [ args["dns_server"] ]
custom_resolver.timeout = custom_resolver.lifetime = args["timeout"]

def eprint(*args, **kwargs):
    print(*args, **kwargs)

#TODO: Add ratelimiting functionality to be able to work with most public DNS resolvers
async def lookup_rdns(ip):
    for _ in range(args["retries"]):
        try:
            resp = await custom_resolver.resolve(ip.reverse_pointer, "PTR")
            responses = [str(x) for x in resp.rrset]
            return (str(ip), responses)
        except NXDOMAIN as exc:
            #The IP has no rDNS record, no need to try again nor log the error
            lastExc = None
            break
        except NoNameservers as exc:
            #The IP most likely either has no delegated authority server or it has one but it's not responding
            if 'SERVFAIL' in str(exc.kwargs["errors"]):
                lastExc = None
            else:
                lastExc = exc
            break
        except Exception as exc:
            #The NS most likely didn't respond or refused the request
            #Uniformly distributed sleep here to avoid sending packets in bursts if they fail
            await asyncio.sleep(rand_uniform(0, args["timeout"]))
            lastExc = exc
            pass
    if(lastExc):
        eprint('Error: ', str(lastExc))


async def run_tasks():
    results = []
    ip_list = list(IPv4Network(args["address"]))
    with alive_bar(len(ip_list)) as progress_bar:
        lastIdx = 0
        pending = set()

        while True:
            for _ in range(args["concurrency"] - len(pending)):
                if lastIdx == len(ip_list):
                    break
                pending.add(asyncio.create_task(lookup_rdns(ip_list[lastIdx])))
                lastIdx+=1

            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            progress_bar(len(done))

            results.extend(filter(lambda x: x is not None, await asyncio.gather(*done)))

            if len(pending) == 0 and lastIdx == len(ip_list):
                return results

sorted_result = sorted(asyncio.run(run_tasks()), key=lambda item: inet_aton(item[0]))
ip_lookup_table = dict(sorted_result)
json_out = json_dump(ip_lookup_table)

if(args["out_file"] is not None):
    with open(args["out_file"], "w+") as f:
        f.write(json_out)
else:
    print(json_out)
