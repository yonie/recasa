DONE

* in events, when you click an event and press back you get sent to top of the page instead of the specific event you clicked which might be found after scrolling down some time.
* when using the browser back button you do not get back to the previous view but somewhere that you were before.
* it seems rescanning all files that were indexed before still takes a lot of time even though nothing is happening? we need to figure out if we can speed that up or if it just is like that because it is hashing?
* it seems rescanning first goes through all files and THEN feeds the list to the pipelines which means it takes a long time. we should have it begin immediately.
* the "scanning files" should have an option to stop further scanning. now i have no way to stop a full rescan which seems to trigger automatically after redeploy.
* we should revise the dockerfile i have a feeling we have some legacy/unused things going on because we used to have CLIP as well and we removed it.
* we should make sure that each pipeline only does "the work" for each photo (hash) once and its stored in the db. so that we dont have to rescan/redo the same work (it takes a long time otherwise)
* we should put the "duplicates" and "large files" menu items in a item called "tools" so they become subitems
* we need to make sure that the search works more intelligently. if i search for "parijs" or "frankrijk" i would expect more hits as im quite sure i have a folder that includes that file name. and if i search for "france" i only get 8 results but if i look on the map i see much more photos taken in france. so this needs to be more intelligent taking exif location data, file paths and so on. we should search for tags aswell.
* events list for some reason only goes back to 2023.
* it seems the pipeline is stuck at Discovered 6.8K In Progress 0 Completed 1.6K Overall 24% with 3 files failed for processing.
* when opening photos, events, people, everything basically we should have the url reflect that, so i can bookmark pages and send direct links to others.
* does the duplicate finder even work? i imagine it would work by taking a lower-resolution photo "hash" which is then used to find highly similar photos even if they are not exactly the same resolution. like a photo hash.
* search for parijs works now.
* events older than 2023 work now.
* stop button works but i want a different icon this is very unclear icon. can also just be a button with the word stop? similar style to the other buttons.
* tools submenu is fine but pipeline should be beneath it, not in the tools section but below it.
* the events all have low res preview images, make it HQ
* clicking an event down the list and pressing back still returns me to top of the list. same happens on people page. same happens on tags page. it doesn't remember my scroll position
* running a rescan should immediately begin feeding files to the pipelines, not when scan ends
* when clicking a "view all" from the map view and pressing back, i suddenly am in a location list instead of the map where i came from
* when i click to view a photo the url does not contain the photo so i still cannot share the link to a photo.
* can we have some kind of color coding on the tags so that it is a bit more dynamic?
* move the "stop" button left of the file name so that it doesn't jump due to length of the file name (its unclickable now)
* we should make sure that a full rescan is only done when the user presses the button, not automatic on startup like it does now. it should just rely on the index it had so far and (hopefully, does it work?) on updates on the fs being caught
* the tags are not colored. they are AI generated so super random, here are some: indoor, outdoor, daytime, sunny, ... we should just have a simple string-to-color function so each has a unique color.
* the tags in the "Tags" page are all grey but im quite sure we have logic to generate unique colors. you said we fixed it but i still see it on the left.
* each time i press rescan, even if NOTHING changed on the photo drive, it begins doing a lot of stuff in the different pipelines. it's like it either forgot it already did things, or the previous rescan did not actually process all files. is there somehow a limit implemented, or are we not correctly storing that we have already processed a file?



TODO


* people remains empty (during scanning?)
* same for events.


* the "years" view only goes back to 2005 and then suddenly 2000 but there are photos in the index of 2004, 2003, 2002 and 2001.
* have proper handling when the frontend is ready but the backend is not yet ready (just after starting the container basically)
* i should be able to click failed items in the pipeline overview to understand what is going wrong
* for files that failed we cannot see which files failed and why.
* the "Stop" button needs to be left of the filename, not to the right of it. you said we fixed it but i still see it on the left.



LONG TERM 



* next to "favorites" we should have a "print" toggle which puts the photos in a "ready to print" folder which can then post to a print on demand service!
