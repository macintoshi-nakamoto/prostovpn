set(NEXA_PRODUCT_NAME "NexaVPN" CACHE STRING "Executable and bundle product name")
set(NEXA_DISPLAY_NAME "Алиса VPN" CACHE STRING "User-facing product name")
set(NEXA_ORGANIZATION_NAME "NexaVPN" CACHE STRING "QSettings organization name")
set(NEXA_HOMEPAGE_URL "https://github.com/amnezia-vpn/amnezia-client" CACHE STRING "Project homepage shown in package metadata")
set(NEXA_SOURCE_URL "https://github.com/amnezia-vpn/amnezia-client" CACHE STRING "Published GPL source URL; set this to the Nexa VPN fork before distributing binaries")
set(NEXA_UPSTREAM_URL "https://github.com/amnezia-vpn/amnezia-client" CACHE STRING "Amnezia VPN upstream source URL")

option(
    NEXA_ENABLE_UPSTREAM_UPDATES
    "Enable update checks against Amnezia-owned stores and release infrastructure"
    OFF
)

