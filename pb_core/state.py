# Holds runtime state shared between the generation hook and the management tab.
# Lives only in memory: cleared when WebUI restarts.
 
last_image = None

# Depth-0 picks of the first image of the last generation per tab (design notes section 15),
# as recorded by parser.expand(..., picks=[...]). Empty until something was generated.
last_picks = {"txt2img": [], "img2img": []}

# True once Script.process() ran for that tab with blocks loaded, even when nothing random was picked
# (design notes 23b: lets "Pin last picks" tell "not generated yet" from "no random picks").
last_generated = {"txt2img": False, "img2img": False}
 