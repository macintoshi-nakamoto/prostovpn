pragma Singleton
import QtQuick

Item {
    id: root

    property var cache: ({})
    property var pending: ({})

    signal resolved(string host)

    function resolve(host) {
        if (!host || host === "") {
            return
        }
        if (cache[host] !== undefined || pending[host]) {
            return
        }
        pending[host] = true

        var xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return
            }
            pending[host] = false

            var entry = null
            try {
                if (xhr.status === 200) {
                    var data = JSON.parse(xhr.responseText)
                    if (data.status === "success") {
                        entry = {
                            country: data.country || "",
                            countryCode: data.countryCode || "",
                            city: data.city || ""
                        }
                    }
                }
            } catch (e) {
                entry = null
            }

            cache[host] = entry
            root.resolved(host)
        }

        xhr.open("GET", "http://ip-api.com/json/" + host + "?fields=status,country,countryCode,city&lang=ru")
        xhr.send()
    }

    function country(host) {
        var entry = cache[host]
        return entry ? entry.country : ""
    }

    function city(host) {
        var entry = cache[host]
        return entry ? entry.city : ""
    }

    function countryCode(host) {
        var entry = cache[host]
        return entry ? entry.countryCode : ""
    }

    function flagSource(host) {
        var code = countryCode(host)
        return code !== "" ? "qrc:/countriesFlags/images/flagKit/" + code.toUpperCase() + ".svg" : ""
    }
}
