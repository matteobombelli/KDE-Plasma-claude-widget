import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as PlasmaSupport
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras

PlasmoidItem {
    id: root

    property real fiveHourPercent: -1
    property real weeklyPercent: -1
    property string fiveHourReset: ""
    property string weeklyReset: ""
    property string lastError: ""
    property bool loading: true
    property bool loggedIn: false
    property string subscriptionType: ""
    property string userEmail: ""

    preferredRepresentation: compactRepresentation
    toolTipMainText: "Claude Usage"
    toolTipSubText: buildTooltip()

    function buildTooltip() {
        if (!loggedIn) return "Not logged in \u2014 click to log in";
        if (loading) return "Loading usage data...";
        if (fiveHourPercent < 0 && weeklyPercent < 0) {
            return lastError ? "Error: " + lastError : "No data available";
        }
        var lines = [];
        if (fiveHourPercent >= 0) {
            lines.push("5-hour limit: " + fiveHourPercent.toFixed(0) + "%");
            if (fiveHourReset) lines.push("  Resets: " + formatReset(fiveHourReset));
        }
        if (weeklyPercent >= 0) {
            lines.push("Weekly limit: " + weeklyPercent.toFixed(0) + "%");
            if (weeklyReset) lines.push("  Resets: " + formatReset(weeklyReset));
        }
        return lines.join("\n");
    }

    function formatReset(resetStr) {
        var num = Number(resetStr);
        var d;
        if (!isNaN(num) && num > 1000000000) {
            d = new Date(num > 9999999999 ? num : num * 1000);
        } else {
            d = new Date(resetStr);
        }
        if (isNaN(d.getTime())) return resetStr;

        var now = new Date();
        var diffMs = d.getTime() - now.getTime();
        if (diffMs <= 0) return "now";

        var diffMins = Math.floor(diffMs / 60000);
        var diffHours = Math.floor(diffMins / 60);
        var remainMins = diffMins % 60;

        var timeStr = d.toLocaleTimeString(Qt.locale(), "HH:mm");
        var dateStr = d.toLocaleDateString(Qt.locale(), "MMM d");

        if (diffHours >= 24) {
            var days = Math.floor(diffHours / 24);
            var remHours = diffHours % 24;
            return "in " + days + "d " + remHours + "h (" + dateStr + " " + timeStr + ")";
        } else if (diffHours > 0) {
            return "in " + diffHours + "h " + remainMins + "m (" + timeStr + ")";
        } else {
            return "in " + remainMins + "m (" + timeStr + ")";
        }
    }

    function parseOutput(stdout) {
        try {
            var data = JSON.parse(stdout);
            loggedIn = data.logged_in || false;
            subscriptionType = data.subscription_type || "";
            userEmail = data.email || "";

            if (data.five_hour_percent !== null && data.five_hour_percent !== undefined) {
                fiveHourPercent = data.five_hour_percent;
            }
            if (data.weekly_percent !== null && data.weekly_percent !== undefined) {
                weeklyPercent = data.weekly_percent;
            }
            fiveHourReset = data.five_hour_reset || "";
            weeklyReset = data.weekly_reset || "";
            lastError = data.error || "";
        } catch (e) {
            lastError = "Parse error: " + e.message;
        }
        loading = false;
    }

    readonly property string fetchScript: "$HOME/.local/bin/claude-usage-fetch"

    // Separate DataSource for fetch commands (output gets parsed)
    PlasmaSupport.DataSource {
        id: fetchSource
        engine: "executable"
        connectedSources: []

        onNewData: function(source, data) {
            var stdout = data["stdout"] || "";
            if (stdout.trim()) {
                root.parseOutput(stdout.trim());
            }
            disconnectSource(source);
        }
    }

    // Separate DataSource for fire-and-forget commands (logout, konsole, etc.)
    PlasmaSupport.DataSource {
        id: cmdSource
        engine: "executable"
        connectedSources: []

        onNewData: function(source, data) {
            disconnectSource(source);
        }
    }

    function fetchData() {
        // Use unique env var to bust DataSource cache without affecting the command
        fetchSource.connectSource("CACHE_BUST=" + Date.now() + " python3 " + fetchScript);
    }

    function fetchCached() {
        fetchSource.connectSource("CACHE_BUST=" + Date.now() + " python3 " + fetchScript + " --cached");
    }

    function runCmd(cmd) {
        cmdSource.connectSource("CACHE_BUST=" + Date.now() + " " + cmd);
    }

    Timer {
        id: refreshTimer
        interval: Plasmoid.configuration.refreshInterval * 60 * 1000
        repeat: true
        running: true
        onTriggered: fetchData()
    }

    Component.onCompleted: {
        fetchCached();
        fetchDelayTimer.start();
    }

    Timer {
        id: fetchDelayTimer
        interval: 2000
        repeat: false
        onTriggered: fetchData()
    }

    compactRepresentation: MouseArea {
        Layout.minimumWidth: rowLayout.implicitWidth + Kirigami.Units.smallSpacing * 2
        Layout.preferredWidth: rowLayout.implicitWidth + Kirigami.Units.smallSpacing * 2
        Layout.fillHeight: true

        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor

        onClicked: root.expanded = !root.expanded

        RowLayout {
            id: rowLayout
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents.Label {
                text: root.loggedIn && root.fiveHourPercent >= 0 ? Math.round(root.fiveHourPercent) + "%" : "--"
                color: "#5B9BD5"
                font.pixelSize: Kirigami.Theme.defaultFont.pixelSize
                font.bold: true
                Layout.alignment: Qt.AlignVCenter
            }

            Image {
                source: "../images/claude-color.svg"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                Layout.alignment: Qt.AlignVCenter
                smooth: true
                fillMode: Image.PreserveAspectFit
            }

            PlasmaComponents.Label {
                text: root.loggedIn && root.weeklyPercent >= 0 ? Math.round(root.weeklyPercent) + "%" : "--"
                color: "#E8913A"
                font.pixelSize: Kirigami.Theme.defaultFont.pixelSize
                font.bold: true
                Layout.alignment: Qt.AlignVCenter
            }
        }
    }

    fullRepresentation: Item {
        implicitWidth: Kirigami.Units.gridUnit * 16
        implicitHeight: contentColumn.implicitHeight + Kirigami.Units.largeSpacing * 2

        ColumnLayout {
            id: contentColumn
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.mediumSpacing

            PlasmaExtras.Heading {
                text: "Claude Usage"
                level: 3
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Kirigami.Theme.disabledTextColor
                opacity: 0.3
            }

            // --- Logged in ---
            ColumnLayout {
                visible: root.loggedIn
                Layout.fillWidth: true
                spacing: Kirigami.Units.mediumSpacing

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Image {
                        source: "../images/claude-color.svg"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                        smooth: true
                        fillMode: Image.PreserveAspectFit
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        PlasmaComponents.Label {
                            text: "Claude " + (root.subscriptionType ? root.subscriptionType.charAt(0).toUpperCase() + root.subscriptionType.slice(1) : "")
                            font.bold: true
                            Layout.fillWidth: true
                        }

                        PlasmaComponents.Label {
                            text: root.userEmail
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                            color: Kirigami.Theme.disabledTextColor
                            Layout.fillWidth: true
                            visible: root.userEmail !== ""
                            elide: Text.ElideRight
                        }
                    }
                }

                // 5-hour usage
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    RowLayout {
                        Layout.fillWidth: true
                        PlasmaComponents.Label {
                            text: "5-Hour Limit"
                            color: "#5B9BD5"
                            font.bold: true
                        }
                        Item { Layout.fillWidth: true }
                        PlasmaComponents.Label {
                            text: root.fiveHourPercent >= 0 ? root.fiveHourPercent.toFixed(0) + "%" : "--"
                            color: "#5B9BD5"
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 6
                        radius: 3
                        color: Kirigami.Theme.backgroundColor
                        border.color: Kirigami.Theme.disabledTextColor
                        border.width: 0.5

                        Rectangle {
                            width: parent.width * Math.min(1, Math.max(0, root.fiveHourPercent / 100))
                            height: parent.height
                            radius: 3
                            color: "#5B9BD5"
                            visible: root.fiveHourPercent >= 0
                        }
                    }

                    PlasmaComponents.Label {
                        text: root.fiveHourReset ? "Resets " + root.formatReset(root.fiveHourReset) : ""
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        color: Kirigami.Theme.disabledTextColor
                        visible: text !== ""
                    }
                }

                // Weekly usage
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    RowLayout {
                        Layout.fillWidth: true
                        PlasmaComponents.Label {
                            text: "Weekly Limit"
                            color: "#E8913A"
                            font.bold: true
                        }
                        Item { Layout.fillWidth: true }
                        PlasmaComponents.Label {
                            text: root.weeklyPercent >= 0 ? root.weeklyPercent.toFixed(0) + "%" : "--"
                            color: "#E8913A"
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 6
                        radius: 3
                        color: Kirigami.Theme.backgroundColor
                        border.color: Kirigami.Theme.disabledTextColor
                        border.width: 0.5

                        Rectangle {
                            width: parent.width * Math.min(1, Math.max(0, root.weeklyPercent / 100))
                            height: parent.height
                            radius: 3
                            color: "#E8913A"
                            visible: root.weeklyPercent >= 0
                        }
                    }

                    PlasmaComponents.Label {
                        text: root.weeklyReset ? "Resets " + root.formatReset(root.weeklyReset) : ""
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        color: Kirigami.Theme.disabledTextColor
                        visible: text !== ""
                    }
                }

                // Refresh interval slider
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Kirigami.Theme.disabledTextColor
                    opacity: 0.3
                    Layout.topMargin: Kirigami.Units.smallSpacing
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    PlasmaComponents.Label {
                        text: "Refresh every " + intervalSlider.value + " min"
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        color: Kirigami.Theme.disabledTextColor
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        PlasmaComponents.Label {
                            text: "1"
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                            color: Kirigami.Theme.disabledTextColor
                        }

                        PlasmaComponents.Slider {
                            id: intervalSlider
                            Layout.fillWidth: true
                            from: 1
                            to: 60
                            stepSize: 1
                            value: Plasmoid.configuration.refreshInterval
                            onMoved: {
                                Plasmoid.configuration.refreshInterval = value;
                            }
                        }

                        PlasmaComponents.Label {
                            text: "60"
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                            color: Kirigami.Theme.disabledTextColor
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Kirigami.Theme.disabledTextColor
                    opacity: 0.3
                }

                PlasmaComponents.Button {
                    text: "Open claude.ai"
                    icon.name: "internet-web-browser"
                    Layout.fillWidth: true
                    onClicked: {
                        Qt.openUrlExternally("https://claude.ai");
                        root.expanded = false;
                    }
                }

                PlasmaComponents.Button {
                    text: "Refresh Now"
                    icon.name: "view-refresh"
                    Layout.fillWidth: true
                    onClicked: {
                        root.loading = true;
                        root.fetchData();
                    }
                }

                PlasmaComponents.Button {
                    text: "Logout"
                    icon.name: "system-log-out"
                    Layout.fillWidth: true
                    onClicked: {
                        runCmd("claude auth logout");
                        runCmd("python3 " + fetchScript + " --logout");
                        root.loggedIn = false;
                        root.fiveHourPercent = -1;
                        root.weeklyPercent = -1;
                        root.userEmail = "";
                        root.expanded = false;
                    }
                }
            }

            // --- Logged out ---
            ColumnLayout {
                visible: !root.loggedIn
                Layout.fillWidth: true
                spacing: Kirigami.Units.mediumSpacing

                PlasmaComponents.Label {
                    text: "Not logged in to Claude Code"
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    color: Kirigami.Theme.disabledTextColor
                }

                PlasmaComponents.Button {
                    text: "Login with Claude Code"
                    icon.name: "user-identity"
                    Layout.fillWidth: true
                    onClicked: {
                        runCmd("konsole -e claude auth login");
                        root.expanded = false;
                        loginCheckTimer.start();
                    }
                }
            }
        }
    }

    // After login, poll a few times to pick up new credentials
    Timer {
        id: loginCheckTimer
        property int attempts: 0
        interval: 10000
        repeat: true
        onTriggered: {
            attempts++;
            fetchData();
            if (root.loggedIn || attempts >= 6) {
                attempts = 0;
                stop();
            }
        }
    }
}
