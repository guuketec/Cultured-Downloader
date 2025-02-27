<script lang="ts">
    import { translate, translateText } from "../scripts/language";
    import { actions } from "../scripts/constants";
    import type { Writable } from "svelte/store";
    import ChibiRakugaki from "../assets/images/chibi-rakugaki-chan.png";
    import { onDestroy, onMount } from "svelte";
    import { tweened } from "svelte/motion";
    import { cubicOut } from "svelte/easing";
    import { Tooltip,  ButtonGroup, Button } from "flowbite-svelte";
    import { BrowserOpenURL } from "../scripts/wailsjs/runtime/runtime";
    import fantiaLogo from "../assets/images/logos/fantia-logo.png";
    import pixivFanboxLogo from "../assets/images/logos/pixiv-fanbox-logo.png";
    import pixivLogo from "../assets/images/logos/pixiv-logo.png";
    import kemonoLogo from "../assets/images/logos/kemono-logo.png";
    import Translate from "./common/Translate.svelte";

    interface Props {
        action: Writable<string>;
        username: Writable<string>;
    }

    let { action, username }: Props = $props();

    const timing = 1000;
    const deg = tweened(0, { 
        duration: timing, 
        easing: cubicOut,
    });
    let interval: number;

    let issueTooltipText = $state("");
    onMount(async () => {
        issueTooltipText = await translateText("Found an issue? Click me!");

        const scale = 10;
        let hasRotateRight = false;
        deg.set(scale);

        interval = setInterval(() => {
            if (hasRotateRight) {
                deg.set(scale);
                hasRotateRight = false;
                return;
            } 

            deg.set(-scale);
            hasRotateRight = true;
        }, timing);
    });

    onDestroy(() => {
        clearInterval(interval);
    });
</script>

<div class="h-screen flex justify-center items-center">
    <div class="text-center">
        <h1 class="text-4xl font-bold mb-4">
            <Translate text="Welcome Back," />
            {$username}<Translate text="!" />
        </h1>
        <p class="mb-2" id="description">{translate("To get started, click on one of the options below or use the navigation bar in the top-left corner.", "description")}</p>
        <ButtonGroup>
            <Button class="dark:!bg-zinc-800 dark:hover:!bg-zinc-500" on:click={() => {action.set(actions.Fantia)}}>
                <img src="{fantiaLogo}" class="w-8 h-8 me-2" alt="fantia logo "/>
                Fantia
            </Button>
            <Button class="dark:!bg-zinc-800 dark:hover:!bg-zinc-500" on:click={() => {action.set(actions.Pixiv)}}>
                <img src="{pixivLogo}" class="w-8 h-8 me-2" alt="pixiv logo "/>
                Pixiv
            </Button>
            <Button class="dark:!bg-zinc-800 dark:hover:!bg-zinc-500" on:click={() => {action.set(actions.PixivFanbox)}}>
                <img src="{pixivFanboxLogo}" class="w-8 h-8 me-2" alt="pixiv fanbox logo "/>
                Pixiv Fanbox
            </Button>
            <Button class="dark:!bg-zinc-800 dark:hover:!bg-zinc-500" on:click={() => {action.set(actions.Kemono)}}>
                <img src="{kemonoLogo}" class="w-8 h-8 me-2" alt="kemono logo "/>
                Kemono
            </Button>
        </ButtonGroup>
    </div>

    <div class="fixed bottom-3 right-0 p-4">
        <button id="issue-btn" type="button" class="bg-main text-white rounded-lg p-2" onclick={() => BrowserOpenURL("https://github.com/KJHJason/Cultured-Downloader/issues")}>
            <img style="transform: rotate({$deg}deg);" src="{ChibiRakugaki}" class="w-24 h-auto" alt="Rakugaki-chan Chibi by Karutamo" />
        </button>
        <Tooltip triggeredBy="#issue-btn" defaultClass="py-2 px-3 text-sm font-medium text-center !bg-gray-200 dark:!bg-zinc-800">
            {issueTooltipText}
        </Tooltip>
    </div>
    <div class="fixed bottom-0 right-0 p-4">
        <p class="text-xs">
            <span id="image-credits">{translate("Image:", "image-credits")}</span>
            <button type="button" id="image-credits-name" class="btn-text-link text-left p-0" onclick={() => BrowserOpenURL("https://www.pixiv.net/users/10600906/artworks")}> 
                {translate("Karutamo", "image-credits-name")}
            </button>
        </p>
    </div>
</div>
