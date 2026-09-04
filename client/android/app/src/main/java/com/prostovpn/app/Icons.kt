package com.prostovpn.app

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

private fun strokeIcon(
    name: String,
    vararg paths: String,
    strokeWidth: Float = 1.8f,
): ImageVector =
    ImageVector.Builder(
        name = name,
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).apply {
        for (d in paths) {
            addPath(
                pathData = addPathNodes(d),
                stroke = SolidColor(Color.White),
                strokeLineWidth = strokeWidth,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            )
        }
    }.build()

private fun fillIcon(name: String, vararg paths: String): ImageVector =
    ImageVector.Builder(
        name = name,
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).apply {
        for (d in paths) {
            addPath(
                pathData = addPathNodes(d),
                fill = SolidColor(Color.White),
            )
        }
    }.build()

object Icons {
    val person: ImageVector by lazy {
        strokeIcon(
            "person",
            "M12 4a4 4 0 1 1 0 8a4 4 0 1 1 0-8",
            "M4 20c1.5-3.5 4.5-5 8-5s6.5 1.5 8 5",
        )
    }

    val lock: ImageVector by lazy {
        strokeIcon(
            "lock",
            "M5 13a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v4a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3z",
            "M8 10V7a4 4 0 0 1 8 0v3",
        )
    }

    val eye: ImageVector by lazy {
        strokeIcon(
            "eye",
            "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z",
            "M12 9.4a2.6 2.6 0 1 1 0 5.2a2.6 2.6 0 1 1 0-5.2",
        )
    }

    val eyeOff: ImageVector by lazy {
        strokeIcon(
            "eyeOff",
            "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z",
            "M12 9.4a2.6 2.6 0 1 1 0 5.2a2.6 2.6 0 1 1 0-5.2",
            "M4 4l16 16",
        )
    }

    val power: ImageVector by lazy {
        strokeIcon(
            "power",
            "M12 3v9",
            "M17.6 6.4a8 8 0 1 1-11.2 0",
            strokeWidth = 2f,
        )
    }

    val gear: ImageVector by lazy {
        strokeIcon(
            "gear",
            "M12 9a3 3 0 1 1 0 6a3 3 0 1 1 0-6",
            "M19.4 15a1.6 1.6 0 0 0 .32 1.76l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.6 1.6 0 0 0-1.76-.32 1.6 1.6 0 0 0-.97 1.47V21a2 2 0 1 1-4 0v-.09a1.6 1.6 0 0 0-1.05-1.47 1.6 1.6 0 0 0-1.76.32l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.6 1.6 0 0 0 .32-1.76 1.6 1.6 0 0 0-1.47-.97H3a2 2 0 1 1 0-4h.09a1.6 1.6 0 0 0 1.47-1.05 1.6 1.6 0 0 0-.32-1.76l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.6 1.6 0 0 0 1.76.32h.09a1.6 1.6 0 0 0 .97-1.47V3a2 2 0 1 1 4 0v.09a1.6 1.6 0 0 0 .97 1.47 1.6 1.6 0 0 0 1.76-.32l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.6 1.6 0 0 0-.32 1.76V9a1.6 1.6 0 0 0 1.47.97H21a2 2 0 1 1 0 4h-.09a1.6 1.6 0 0 0-1.47.97z",
        )
    }

    val chevronUp: ImageVector by lazy {
        strokeIcon("chevronUp", "M6 15l6-6 6 6", strokeWidth = 2f)
    }

    val chevronDown: ImageVector by lazy {
        strokeIcon("chevronDown", "M6 9l6 6 6-6", strokeWidth = 2f)
    }

    val chevronRight: ImageVector by lazy {
        strokeIcon("chevronRight", "M9 6l6 6-6 6", strokeWidth = 2f)
    }

    val chevronLeft: ImageVector by lazy {
        strokeIcon("chevronLeft", "M15 6l-6 6 6 6", strokeWidth = 2.2f)
    }

    val globe: ImageVector by lazy {
        strokeIcon(
            "globe",
            "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18",
            "M3 12h18",
            "M12 3c2.5 2.5 3.8 5.6 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.6-3.8-9S9.5 5.5 12 3z",
        )
    }

    val check: ImageVector by lazy {
        strokeIcon("check", "M5 13l5 5 9-11", strokeWidth = 2.4f)
    }

    val telegram: ImageVector by lazy {
        fillIcon(
            "telegram",
            "M21.9 4.6L18.8 19c-.2 1-.9 1.3-1.7.8l-4.7-3.5-2.3 2.2c-.3.3-.5.5-1 .5l.3-4.8L18 6.3c.4-.3-.1-.5-.6-.2L6.6 13 2 11.5c-1-.3-1-1 .2-1.5l17.9-6.9c.9-.3 1.7.2 1.8 1.5z",
        )
    }

    val help: ImageVector by lazy {
        strokeIcon(
            "help",
            "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18",
            "M9.5 9a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 2.2-2.4 3.7",
            "M12 16.6v0.4",
        )
    }

    val star: ImageVector by lazy {
        strokeIcon(
            "star",
            "M12 3.6l2.47 5.02 5.53.8-4 3.9.94 5.5L12 16.2l-4.94 2.6.94-5.5-4-3.9 5.53-.8z",
        )
    }

    val doc: ImageVector by lazy {
        strokeIcon(
            "doc",
            "M6.5 4.5a2 2 0 0 1 2-2h4.6L18.5 7.9V19.5a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2z",
            "M13 2.7v5.4h5.4",
        )
    }

    val docText: ImageVector by lazy {
        strokeIcon(
            "docText",
            "M6.5 4.5a2 2 0 0 1 2-2h4.6L18.5 7.9V19.5a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2z",
            "M13 2.7v5.4h5.4",
            "M9.5 12.5h5",
            "M9.5 16h5",
        )
    }

    val plus: ImageVector by lazy {
        strokeIcon("plus", "M12 5v14", "M5 12h14", strokeWidth = 2.2f)
    }

    val trash: ImageVector by lazy {
        strokeIcon(
            "trash",
            "M4 7h16",
            "M9.2 7V5.4a1.6 1.6 0 0 1 1.6-1.6h2.4a1.6 1.6 0 0 1 1.6 1.6V7",
            "M6.3 7l.75 12a2 2 0 0 0 2 1.9h5.9a2 2 0 0 0 2-1.9L17.7 7",
            "M10 11.2v5.6",
            "M14 11.2v5.6",
        )
    }

    val upload: ImageVector by lazy {
        strokeIcon(
            "upload",
            "M8 9.5H6.8A1.8 1.8 0 0 0 5 11.3v7.4a1.8 1.8 0 0 0 1.8 1.8h10.4a1.8 1.8 0 0 0 1.8-1.8v-7.4a1.8 1.8 0 0 0-1.8-1.8H16",
            "M12 14V3.4",
            "M8.5 6.7L12 3.2l3.5 3.5",
        )
    }

    val bell: ImageVector by lazy {
        strokeIcon(
            "bell",
            "M18 10a6 6 0 1 0-12 0c0 4.2-1.4 5.6-1.9 6.1a.6.6 0 0 0 .43 1.02h14.94a.6.6 0 0 0 .43-1.02C19.4 15.6 18 14.2 18 10",
            "M10.3 20.2a2 2 0 0 0 3.4 0",
        )
    }

    /** «Ещё» — лучистая точка: не три полоски и не шестерёнка. */
    val more: ImageVector by lazy {
        strokeIcon(
            "more",
            "M12 9.4a2.6 2.6 0 1 1 0 5.2a2.6 2.6 0 1 1 0-5.2",
            "M12 2.6v2.6",
            "M12 18.8v2.6",
            "M2.6 12h2.6",
            "M18.8 12h2.6",
            "M5.4 5.4l1.8 1.8",
            "M16.8 16.8l1.8 1.8",
            "M18.6 5.4l-1.8 1.8",
            "M7.2 16.8l-1.8 1.8",
            strokeWidth = 1.9f,
        )
    }

    val zap: ImageVector by lazy {
        strokeIcon("zap", "M13.2 2.6L4.8 13.2h6L10.2 21.4l8.4-10.6h-6z", strokeWidth = 1.9f)
    }

    val mail: ImageVector by lazy {
        strokeIcon(
            "mail",
            "M3 7.6a2.6 2.6 0 0 1 2.6-2.6h12.8A2.6 2.6 0 0 1 21 7.6v8.8a2.6 2.6 0 0 1-2.6 2.6H5.6A2.6 2.6 0 0 1 3 16.4z",
            "M3.6 7l7.3 5.2a2 2 0 0 0 2.2 0L20.4 7",
        )
    }

    val copy: ImageVector by lazy {
        strokeIcon(
            "copy",
            "M9 9.4a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2z",
            "M15 7.2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h1.2",
        )
    }

    val logout: ImageVector by lazy {
        strokeIcon(
            "logout",
            "M14.5 4.6H17a2.4 2.4 0 0 1 2.4 2.4v10a2.4 2.4 0 0 1-2.4 2.4h-2.5",
            "M10 15.6L13.6 12L10 8.4",
            "M13.2 12H4.6",
        )
    }

    val shield: ImageVector by lazy {
        strokeIcon(
            "shield",
            "M12 3l7 2.6v5.9c0 4.2-2.8 7.7-7 9.5-4.2-1.8-7-5.3-7-9.5V5.6z",
            "M9 12.2l2.1 2.1 4-4.2",
        )
    }

    val refresh: ImageVector by lazy {
        strokeIcon(
            "refresh",
            "M20 12a8 8 0 1 1-2.4-5.7",
            "M20.4 4.2v4.4h-4.4",
            strokeWidth = 2f,
        )
    }

    val wifiOff: ImageVector by lazy {
        strokeIcon(
            "wifiOff",
            "M3 4l18 16",
            "M4.4 9.4a15 15 0 0 1 4.2-2.6",
            "M19.6 9.4a15 15 0 0 0-6.6-3",
            "M7.6 13a9.4 9.4 0 0 1 2-1.3",
            "M16.4 13a9.4 9.4 0 0 0-1.5-1",
            "M12 18.2v.2",
        )
    }

    val sad: ImageVector by lazy {
        strokeIcon(
            "sad",
            "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18",
            "M8.6 15.6a4.6 4.6 0 0 1 6.8 0",
            "M9 9.6v.6",
            "M15 9.6v.6",
            strokeWidth = 1.9f,
        )
    }
}
