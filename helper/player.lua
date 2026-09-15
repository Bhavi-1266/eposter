-- Countdown and input live in the same window as all media. No Tk/X11 overlay.
local mp = require 'mp'
local utils = require 'mp.utils'
local state = {rotation = 0, footer_left = '', footer_right = '', status = ''}
local overlay = mp.create_osd_overlay('ass-events')
local previous = ''

local function escape(text)
    return tostring(text or ''):gsub('\\', '\\' .. '\239\187\191'):gsub('{', '\\{'):gsub('}', '\\}'):gsub('\n', '\\N')
end

local function render()
    local deadline = tonumber(state.deadline)
    local left = deadline and math.max(0, math.ceil(deadline - os.time())) or nil
    local countdown = left and tostring(left) or ''
    if countdown ~= state.last_countdown then
        mp.commandv('script-message', 'eposter-state', 'countdown', countdown)
        state.last_countdown = countdown
    end
    local w, h = mp.get_osd_size()
    if not w or w <= 0 or h <= 0 then return end
    local rotation = tonumber(state.rotation) or 0
    local lw, lh = w, h
    if rotation == 90 or rotation == 270 then lw, lh = h, w end
    -- Keep in sync with overlay_scale/uncover_overlays in display_handler.py.
    local scale = math.max(0.75, math.min(w, h) / 1080)
    local lines = {}
    local function position(x, y)
        if rotation == 90 then return w-y, x end
        if rotation == 180 then return w-x, h-y end
        if rotation == 270 then return y, h-x end
        return x, y
    end
    local function tags(x, y, alignment)
        local px, py = position(x, y)
        return string.format('\\rDefault\\fscx100\\fscy100\\an%d\\pos(%.2f,%.2f)\\frz%d\\bord0\\shad0', alignment or 7, px, py, -rotation)
    end
    local function text(x, y, value, size, color, alignment)
        lines[#lines+1] = '{' .. tags(x,y,alignment) .. '\\fnDejaVu Sans Mono\\fs' .. size .. '\\1c&H' .. color .. '&}' .. escape(value)
    end
    local function box(x, y, width, height, color, alpha, radius)
        local r = radius or 0
        local path = string.format('m %d 0 l %d 0 b %d 0 %d 0 %d %d l %d %d b %d %d %d %d %d %d l %d %d b 0 %d 0 %d 0 %d l 0 %d b 0 0 0 0 %d 0',
            r,width-r,width,width,width,r,width,height-r,width,height,width,height,width-r,height,r,height,height,height,height-r,r,r)
        lines[#lines+1] = '{' .. tags(x,y) .. '\\1c&H' .. color .. '&\\1a&H' .. alpha .. '&\\p1}' .. path .. '{\\p0}'
    end
    if deadline then
        local value = string.format('%02d:%02d', math.floor(left/60), left%60)
        local size = math.floor(28*scale)
        local width = math.max(120*scale, #value*size*0.65 + 24*scale)
        box(16*scale,16*scale,width,48*scale,'DEF0F8','30',math.floor(16*scale))
        text(28*scale,23*scale,value,size,'2C3841')
    end
    -- The renderer reserves this strip outside the media viewport.
    local footer_height = math.floor(56*scale + 0.5)
    box(0,lh-footer_height,lw,footer_height,'F5F5F5','00',0)
    text(16*scale,lh-footer_height+8*scale,state.footer_left or '',math.floor(32*scale),'2D2D2D')
    text(lw-16*scale,lh-footer_height+8*scale,state.footer_right or '',math.floor(32*scale),'2D2D2D',9)
    if state.status and state.status ~= '' then
        local size = math.max(18, math.floor(lw/45))
        local value = tostring(state.status)
        local x = math.max(24, (lw - #value*size*0.6)/2)
        box(0,lh/2-12,lw,size*2.2,'000000','30',0)
        text(x,lh/2,value,size,'FFFFFF')
    end
    local data = table.concat(lines, '\n')
    local key = data .. w .. ':' .. h
    if key == previous then return end
    previous = key
    overlay.res_x, overlay.res_y, overlay.data = w, h, data
    overlay:update()
end

mp.register_script_message('eposter-overlay', function(json)
    local parsed = utils.parse_json(json)
    if parsed then state = parsed; previous = ''; render() end
end)
mp.observe_property('osd-dimensions', 'native', function() previous = ''; render() end)
mp.add_periodic_timer(0.1, render)

local function send(key, x, y)
    mp.commandv('script-message', 'eposter-input', key, tostring(x or 0), tostring(y or 0))
end
for _, key in ipairs({'q','ESC','ENTER','SPACE','UP','DOWN','PGUP','PGDWN','WHEEL_UP','WHEEL_DOWN'}) do
    mp.add_forced_key_binding(key, 'eposter-' .. key, function() send(key) end, {repeatable=true})
end
local press = nil
mp.add_forced_key_binding('MBTN_LEFT', 'eposter-click', function(event)
    local x, y = mp.get_mouse_pos()
    if event.event == 'down' then
        press = {x=x, y=y}
    elseif event.event == 'up' then
        if press and math.abs(y-press.y) + math.abs(x-press.x) > 15 then
            send('DRAG', x-press.x, y-press.y)
        else
            send('CLICK', x, y)
        end
        press = nil
    elseif event.event == 'press' then
        send('CLICK', x, y)
    end
end, {complex=true})
-- Prevent default double click fullscreen toggles and right click actions.
mp.add_forced_key_binding('MBTN_LEFT_DBL', 'eposter-double', function() end)
mp.add_forced_key_binding('MBTN_RIGHT', 'eposter-right', function() send('ESC') end)

mp.register_script_message('eposter-ping', function()
    mp.commandv('script-message', 'eposter-state', 'ready', '1')
end)
