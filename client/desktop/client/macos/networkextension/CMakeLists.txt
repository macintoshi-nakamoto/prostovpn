enable_language(Swift)
message("Client message >> macos build >> NexaVPNNetworkExtension")
set(CLIENT_ROOT_DIR ${CMAKE_CURRENT_LIST_DIR}/../..)

add_executable(NexaVPNNetworkExtension)

message("executable_path is: @executable_path/../../Frameworks")
set_target_properties(NexaVPNNetworkExtension PROPERTIES
    XCODE_PRODUCT_TYPE com.apple.product-type.app-extension
    # MACOSX_BUNDLE YES
    BUNDLE_EXTENSION appex
    MACOSX_BUNDLE_SHORT_VERSION_STRING "${APPLE_PROJECT_VERSION}"
    MACOSX_BUNDLE_INFO_STRING "NexaVPNNetworkExtension"
    MACOSX_BUNDLE_BUNDLE_NAME "NexaVPNNetworkExtension"
    XCODE_ATTRIBUTE_PRODUCT_BUNDLE_IDENTIFIER "${BUILD_OSX_APP_IDENTIFIER}.network-extension"
    XCODE_ATTRIBUTE_PRODUCT_BUNDLE_NAME "${BUILD_OSX_APP_IDENTIFIER}.network-extension"
    XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS ${CMAKE_CURRENT_SOURCE_DIR}/NexaVPNNetworkExtension.entitlements
    XCODE_ATTRIBUTE_MARKETING_VERSION "${APP_MAJOR_VERSION}"
    XCODE_ATTRIBUTE_CURRENT_PROJECT_VERSION "${CMAKE_PROJECT_VERSION_TWEAK}"
    XCODE_ATTRIBUTE_PRODUCT_NAME "NexaVPNNetworkExtension"

    XCODE_ATTRIBUTE_APPLICATION_EXTENSION_API_ONLY "YES"
    XCODE_ATTRIBUTE_ENABLE_BITCODE "NO"
    XCODE_ATTRIBUTE_MACOSX_DEPLOYMENT_TARGET "11.0"

    XCODE_ATTRIBUTE_INFOPLIST_FILE ${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in
    XCODE_ATTRIBUTE_LD_RUNPATH_SEARCH_PATHS "@executable_path/../../../../Frameworks @loader_path/../../../../Frameworks"

    XCODE_LINK_BUILD_PHASE_MODE KNOWN_LOCATION
)

if(DEPLOY)
    message("DEPLOY is ON")
    if(NOT BUILD_MACOS_EXTENSION_PROFILE OR NOT BUILD_MACOS_EXTENSION_PROFILE_DEBUG)
        message(FATAL_ERROR "DEPLOY requires BUILD_MACOS_EXTENSION_PROFILE and BUILD_MACOS_EXTENSION_PROFILE_DEBUG")
    endif()
    set_target_properties(NexaVPNNetworkExtension PROPERTIES
        XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY "Apple Distribution"
        XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY[variant=Debug] "Apple Development"
        XCODE_ATTRIBUTE_CODE_SIGN_STYLE Manual
        XCODE_ATTRIBUTE_PROVISIONING_PROFILE_SPECIFIER "${BUILD_MACOS_EXTENSION_PROFILE}"
        XCODE_ATTRIBUTE_PROVISIONING_PROFILE_SPECIFIER[variant=Debug] "${BUILD_MACOS_EXTENSION_PROFILE_DEBUG}"
    )
else()
    set_target_properties(NexaVPNNetworkExtension PROPERTIES
        XCODE_ATTRIBUTE_CODE_SIGN_STYLE Automatic
    )
endif()

set_target_properties(NexaVPNNetworkExtension PROPERTIES
    XCODE_ATTRIBUTE_SWIFT_VERSION "5.0"
    XCODE_ATTRIBUTE_CLANG_ENABLE_MODULES "YES"
    XCODE_ATTRIBUTE_SWIFT_OBJC_BRIDGING_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/WireGuardNetworkExtension-Bridging-Header.h"
    XCODE_ATTRIBUTE_SWIFT_OPTIMIZATION_LEVEL "-Onone"
    XCODE_ATTRIBUTE_SWIFT_PRECOMPILE_BRIDGING_HEADER "NO"
)

if(BUILD_VPN_DEVELOPMENT_TEAM)
    set_target_properties(NexaVPNNetworkExtension PROPERTIES
        XCODE_ATTRIBUTE_DEVELOPMENT_TEAM "${BUILD_VPN_DEVELOPMENT_TEAM}"
    )
endif()

find_library(FW_ASSETS_LIBRARY AssetsLibrary)
find_library(FW_MOBILE_CORE MobileCoreServices)
find_library(FW_UI_KIT UIKit)
find_library(FW_LIBRESOLV libresolv.9.tbd)


# Set the root directory
set(CLIENT_ROOT_DIR ${CMAKE_CURRENT_LIST_DIR}/../..)

target_link_libraries(NexaVPNNetworkExtension PRIVATE ${FW_LIBRESOLV})

target_compile_options(NexaVPNNetworkExtension PRIVATE -DGROUP_ID=\"${BUILD_OSX_GROUP_IDENTIFIER}\")
target_compile_options(NexaVPNNetworkExtension PRIVATE -DNETWORK_EXTENSION=1)

set(WG_APPLE_SOURCE_DIR ${CLIENT_ROOT_DIR}/3rd/amneziawg-apple/Sources)

message("WG_APPLE_SOURCE_DIR is: ${WG_APPLE_SOURCE_DIR}")
message("CLIENT_ROOT_DIR is: ${CLIENT_ROOT_DIR}")

target_sources(NexaVPNNetworkExtension PRIVATE
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/WireGuardAdapter.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/PacketTunnelSettingsGenerator.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/DNSResolver.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardNetworkExtension/ErrorNotifier.swift
    ${WG_APPLE_SOURCE_DIR}/Shared/Keychain.swift
    ${WG_APPLE_SOURCE_DIR}/Shared/Model/TunnelConfiguration+WgQuickConfig.swift
    ${WG_APPLE_SOURCE_DIR}/Shared/Model/NETunnelProviderProtocol+Extension.swift
    ${WG_APPLE_SOURCE_DIR}/Shared/Model/String+ArrayConversion.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/TunnelConfiguration.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/IPAddressRange.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/Endpoint.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/DNSServer.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/InterfaceConfiguration.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/PeerConfiguration.swift
    ${WG_APPLE_SOURCE_DIR}/Shared/FileManager+Extension.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKitC/x25519.c
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/Array+ConcurrentMap.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/IPAddress+AddrInfo.swift
    ${WG_APPLE_SOURCE_DIR}/WireGuardKit/PrivateKey.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/HevSocksTunnel.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/NELogController.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/Log.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/LogRecord.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/PacketTunnelProvider.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/PacketTunnelProvider+WireGuard.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/PacketTunnelProvider+OpenVPN.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/PacketTunnelProvider+Xray.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/WGConfig.swift
    ${CLIENT_ROOT_DIR}/platforms/ios/iosglue.mm
    ${CLIENT_ROOT_DIR}/platforms/ios/XrayConfig.swift
)

target_sources(NexaVPNNetworkExtension PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/PrivacyInfo.xcprivacy
)

set_property(TARGET NexaVPNNetworkExtension APPEND PROPERTY RESOURCE
    ${CMAKE_CURRENT_SOURCE_DIR}/PrivacyInfo.xcprivacy
)

target_include_directories(NexaVPNNetworkExtension PRIVATE ${CLIENT_ROOT_DIR})
target_include_directories(NexaVPNNetworkExtension PRIVATE ${CMAKE_CURRENT_BINARY_DIR})

find_package(openvpnadapter REQUIRED)
# FIXME(ygurov): https://github.com/conan-io/conan/issues/20034
set_property(TARGET amnezia::openvpnadapter APPEND PROPERTY IMPORTED_CONFIGURATIONS DEBUG)
set_property(TARGET amnezia::openvpnadapter APPEND PROPERTY IMPORTED_CONFIGURATIONS MINSIZEREL)
set_property(TARGET amnezia::openvpnadapter APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_property(TARGET amnezia::openvpnadapter APPEND PROPERTY IMPORTED_CONFIGURATIONS RELWITHDEBINFO)
target_link_libraries(NexaVPNNetworkExtension PRIVATE amnezia::openvpnadapter)

find_package(awg-apple REQUIRED)
target_link_libraries(NexaVPNNetworkExtension PRIVATE amnezia::awg-apple)

find_package(hev-socks5-tunnel REQUIRED)
# FIXME(ygurov): https://github.com/conan-io/conan/issues/20034
set_property(TARGET heiher::hev-socks5-tunnel APPEND PROPERTY IMPORTED_CONFIGURATIONS DEBUG)
set_property(TARGET heiher::hev-socks5-tunnel APPEND PROPERTY IMPORTED_CONFIGURATIONS MINSIZEREL)
set_property(TARGET heiher::hev-socks5-tunnel APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_property(TARGET heiher::hev-socks5-tunnel APPEND PROPERTY IMPORTED_CONFIGURATIONS RELWITHDEBINFO)
target_link_libraries(NexaVPNNetworkExtension PRIVATE heiher::hev-socks5-tunnel)
