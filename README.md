# CloudFlare hook for dehydrated

This is a hook for [dehydrated](https://github.com/lukas2511/dehydrated) that allows you to use [CloudFlare](https://www.cloudflare.com/)
DNS records to respond to dns-01 challenges.

## Dependencies

* Python 3
 * cloudflare
 * dnspython

You can install all python modules with `pip install -r requirements.txt`.

## Configuration

The configuration for this hook is expected in the environment. Following variables are used:

| Environment variable | Description                                                             | Default                                            |
| -------------------- | ----------------------------------------------------------------------- | -------------------------------------------------- |
| CF_API_EMAIL         | Your CloudFlare account's E-Mail address                                |                                                    |
| CF_API_KEY           | Your CloudFlare account's api key                                       |                                                    |
| CF_DNS_SERVERS       | Comma-separated list of DNS server(s) to check if record is propagated. | Empty, will use your resolvers in /etc/resolv.conf |
| CF_CACHEFILE         | Where to store your cloudflare cache.                                   | /etc/dehydrated/cloudflare.json                    |
| CF_CACHEFMODE        | Change file permissions to this.                                        | 600                                                |
| CF_CACHETIME         | How long the results should be cached in seconds.                       | 2592000                                            |
| CF_DEBUG             | Enable debug output.                                                    | False                                              |

## Cache

This hook will cache some results from cloudflare which are likly not change in a while. Per default the cache file is stored in */etc/dehydrated/cloudflare.json*. To prevent data-exposure the permissions for this file is changed to *600* (rw- --- ---).

The cache can be disabled by exporting an empty CF_CACHEFILE variable: `export CF_CACHEFILE=`

Currently only zone ids are cached.
