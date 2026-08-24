# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class cn.chiyaole.net.** { *** Companion; }
-keep,includedescriptorclasses class cn.chiyaole.**$$serializer { *; }
-keepclassmembers class cn.chiyaole.** { *** Companion; }
-keepclasseswithmembers class cn.chiyaole.** { kotlinx.serialization.KSerializer serializer(...); }
