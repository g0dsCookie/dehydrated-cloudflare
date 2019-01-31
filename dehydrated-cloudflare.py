#!/usr/bin/env python3
from argparse import ArgumentParser
import CloudFlare
import dns
import json
import logging
import os
import sys
import time


def _iter_domain(domain):
    dom = domain.split(".")
    dom_idx = len(dom)
    while dom_idx > 0:
        yield ".".join(dom[dom_idx-1:])
        dom_idx -= 1


class CloudFlareHook:
    def __init__(self, argv=None):
        self._log = logging.getLogger("CloudFlare")
        self._init_log()
        self._cf = CloudFlare.CloudFlare()
        self._zone_id_cache = {}
        self._cache_changed = False

    def _dns_propagated(self, name, token):
        dns_servers = os.environ.get("CF_DNS_SERVERS")
        if dns_servers:
            resolver = dns.resolver.Resolver()
            resolver.nameservers = dns_servers.split(",")
            resolver_fn = resolver.query
        else:
            resolver_fn = dns.resolver.query

        try:
            response = resolver_fn(name, "TXT")
        except dns.exception.DNSException as err:
            self._log.debug("%s. Retrying query...", err)
            return False

        for rdata in response:
            if token in [s.decode("utf8") for s in rdata.strings]:
                return True
        return False

    def _init_log(self):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt=" + %(message)s"))
        self._log.addHandler(handler)
        self._log.setLevel(logging.DEBUG if os.environ.get("CF_DEBUG") else logging.INFO)

    def _zone_id_from_cache(self, domain):
        if domain in self._zone_id_cache:
            if time.time() - self._zone_id_cache[domain]["created"] >= int(os.environ.get("CF_CACHETIME", 30*24*60*60)):
                del self._zone_id_cache[domain]
                self._log.debug("Invalidating cache for %s", domain)
                return None
            return self._zone_id_cache[domain]["id"]
        return None

    def _zone_id_to_cache(self, domain, zone_id):
        self._zone_id_cache[domain] = {"id": zone_id, "created": time.time()}
        self._cache_changed = True
        return zone_id

    def _get_zone_id(self, domain):
        for dom in _iter_domain(domain):
            zone_id = self._zone_id_from_cache(dom)
            if zone_id:
                self._log.debug("Using cached zone id for %s: %s", domain, zone_id)
                return zone_id

            zones = self._cf.zones.get(params = {"name": dom})
            if len(zones) == 0:
                self._log.debug("%s not found while querying %s", dom, domain)
                self._zone_id_to_cache(dom, None)
                continue
            elif len(zones) > 1:
                self._log.warning("Found multiple zones for %s", dom)
            
            self._log.debug("Found zone id %s for domain %s", zones[0]["id"], domain)
            return self._zone_id_to_cache(dom, zones[0]["id"])

        self._log.error("No zone found for domain %s", domain)

    def _get_txt_record_id(self, zone_id, name, token):
        records = self._cf.zones.dns_records.get(zone_id, params = {"type": "TXT", "name": name, "content": token})
        if len(records) == 0:
            self._log.debug("Unable to locate TXT record named %s with content %s", name, token)
            return None
        elif len(records) > 1:
            self._log.warning("Found multiple TXT records named %s with content %s", name, token)
        
        return records[0]["id"]

    def _deploy_challenge(self, domain, token_filename, token_value):
        self._log.debug("Deploying challenge %s for %s", token_value, domain)

        zone_id = self._get_zone_id(domain)
        record_name = "_acme-challenge.%s" % domain
        record_id = self._get_txt_record_id(zone_id, record_name, token_value)
        if record_id:
            self._log.debug("TXT record already exists, skipping creation")
            return

        new_record = {
            "name": record_name,
            "type": "TXT",
            "content": token_value,
            "ttl": 120,
        }
        try:
            result = self._cf.zones.dns_records.post(zone_id, data=new_record)
        except CloudFlare.exceptions.CloudFlareAPIError as err:
            self._log.error("Failed to create %s: %s", record_name, err)
            return
        self._log.debug("Created _acme-challenge.%s with id %s", domain, result["id"])

        while not self._dns_propagated(record_name, token_value):
            self._log.info("DNS not propagated for %s, waiting 10 seconds...", record_name)
            time.sleep(10)

    def _clean_challenge(self, domain, token_filename, token_value):
        self._log.debug("Cleaning challenge %s for %s", token_value, domain)

        zone_id = self._get_zone_id(domain)
        record_name = "_acme-challenge.%s" % domain
        record_id = self._get_txt_record_id(zone_id, record_name, token_value)

        if not record_id:
            self._log.debug("No TXT record found for %s", domain)
            return
    
        try:
            self._cf.zones.dns_records.delete(zone_id, record_id)
        except CloudFlare.exceptions.CloudFlareAPIError as err:
            self._log.error("Failed to delete TXT record for %s: %s", record_name, err)
            return
        self._log.info("Deleted TXT record %s", record_name)

    def _load_cache(self, fname):
        if not os.path.isfile(fname):
            self._log.info("Cache file %s not found", fname)
            return
        with open(fname) as file:
            cache_file = json.load(file)
            if cache_file["account"] != os.environ.get("CF_API_EMAIL"):
                self._log.warning("Not using cache for invalid account %s", cache_file["account"])
                return
            self._zone_id_cache = cache_file["zone"]
            self._cache_changed = False
        self._log.debug("Cache loaded from %s", fname)

    def _save_cache(self, fname):
        if not self._cache_changed:
            self._log.debug("Cache has not changed")
            return
        with open(fname, "w") as file:
            json.dump({"account": os.environ.get("CF_API_EMAIL"), "zone": self._zone_id_cache}, file)
        os.chmod(fname, int(os.environ.get("CF_CACHEFMODE", "600"), base=8))
        self._log.debug("Cache saved to %s", fname)

    def main(self, argv):
        actions = {
            "deploy_challenge": self._deploy_challenge,
            "clean_challenge": self._clean_challenge,
        }
        cache_fname = os.environ.get("CF_CACHEFILE", "/etc/dehydrated/cloudflare.json")
        op = argv[0]
        if op in actions:
            self._log.debug("CloudFlare hook executing: %s", op)
            self._load_cache(cache_fname)
            actions[op](*argv[1:])
            self._save_cache(cache_fname)
        else:
            self._log.debug("Unknown action: %s", op)


if __name__ == "__main__":
    CloudFlareHook().main(sys.argv[1:])
