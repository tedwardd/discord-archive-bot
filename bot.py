import os
import re
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from urllib.parse import urlparse

from database import init_db, add_watched_site, remove_watched_site, get_watched_sites, is_watched_site
from archive_service import ArchiveService

load_dotenv()

# URL regex pattern
URL_PATTERN = re.compile(
    r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*',
    re.IGNORECASE
)


class ArchiveBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        
        prefix = os.getenv("COMMAND_PREFIX", "!")
        super().__init__(command_prefix=prefix, intents=intents, help_command=None)
        
        self.archive_service = ArchiveService()
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        await init_db()
        await self.add_cog(SiteManagementCog(self))
        await self.add_cog(ArchiveCog(self))
        # Sync slash commands
        await self.tree.sync()
    
    async def close(self):
        """Cleanup when bot shuts down."""
        await self.archive_service.close()
        await super().close()


class SiteManagementCog(commands.Cog, name="Site Management"):
    """Commands for managing the watched sites list."""
    
    def __init__(self, bot: ArchiveBot):
        self.bot = bot
    
    @commands.hybrid_command(name="addsite", description="Add a domain to the watched sites list")
    @app_commands.describe(domain="The domain to add (e.g., nytimes.com)")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def add_site(self, ctx: commands.Context, domain: str):
        """Add a domain to the watched sites list."""
        # Clean up the domain
        domain = domain.lower().strip()
        if domain.startswith("http"):
            parsed = urlparse(domain)
            domain = parsed.netloc
        
        # Remove www. prefix if present
        if domain.startswith("www."):
            domain = domain[4:]
        
        if not domain:
            await ctx.send("Please provide a valid domain.")
            return
        
        added = await add_watched_site(str(ctx.guild.id), domain, str(ctx.author))
        if added:
            await ctx.send(f"Added `{domain}` to the watched sites list.")
        else:
            await ctx.send(f"`{domain}` is already in the watched sites list.")
    
    @commands.hybrid_command(name="removesite", description="Remove a domain from the watched sites list")
    @app_commands.describe(domain="The domain to remove")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def remove_site(self, ctx: commands.Context, domain: str):
        """Remove a domain from the watched sites list."""
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        
        removed = await remove_watched_site(str(ctx.guild.id), domain)
        if removed:
            await ctx.send(f"Removed `{domain}` from the watched sites list.")
        else:
            await ctx.send(f"`{domain}` was not in the watched sites list.")
    
    @commands.hybrid_command(name="listsites", description="List all sites being monitored for archiving")
    @commands.guild_only()
    async def list_sites(self, ctx: commands.Context):
        """List all domains in the watched sites list."""
        sites = await get_watched_sites(str(ctx.guild.id))
        
        if not sites:
            await ctx.send("No sites are currently being monitored.")
            return
        
        # Format the list nicely
        site_list = "\n".join(f"• `{site}`" for site in sites)
        
        embed = discord.Embed(
            title="Monitored Sites",
            description=site_list,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total: {len(sites)} sites")
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="archivehelp", description="Show Archive Bot commands")
    async def archive_help(self, ctx: commands.Context):
        """Show help for Archive Bot commands."""
        prefix = os.getenv("COMMAND_PREFIX", "!")
        
        embed = discord.Embed(
            title="Archive Bot Help",
            description="Automatically detects URLs from watched sites and provides archived versions.",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name=f"{prefix}archive <url>",
            value="Get archived version of any URL",
            inline=False
        )
        embed.add_field(
            name=f"{prefix}listsites",
            value="List all monitored sites",
            inline=False
        )
        embed.add_field(
            name=f"{prefix}addsite <domain>",
            value="Add a site to watch (requires Manage Messages)",
            inline=False
        )
        embed.add_field(
            name=f"{prefix}removesite <domain>",
            value="Remove a watched site (requires Manage Messages)",
            inline=False
        )
        
        embed.set_footer(text="Tip: Slash commands (/archive, /listsites, etc.) also work!")
        
        await ctx.send(embed=embed)


class ArchiveCog(commands.Cog, name="Archive"):
    """Commands and listeners for archive functionality."""
    
    def __init__(self, bot: ArchiveBot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages containing URLs from watched sites."""
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        # Find all URLs in the message
        urls = URL_PATTERN.findall(message.content)
        
        if not urls:
            return
        
        watched_sites = await get_watched_sites(str(message.guild.id))
        if not watched_sites:
            return
        
        for url in urls:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                
                # Remove www. prefix for matching
                if domain.startswith("www."):
                    domain = domain[4:]
                
                # Check if this domain matches any watched site
                is_watched = any(
                    watched_domain in domain or domain in watched_domain
                    for watched_domain in watched_sites
                )
                
                if is_watched:
                    await self._handle_watched_url(message, url)
                    
            except Exception as e:
                print(f"Error processing URL {url}: {e}")
    
    async def _handle_watched_url(self, message: discord.Message, url: str):
        """Handle a URL from a watched site."""
        async with message.channel.typing():
            result = await self.bot.archive_service.get_archive(url)
        
        embed = discord.Embed(
            title="Archived Version",
            color=discord.Color.blue()
        )
        
        # Wayback Machine result
        if result.wayback_url:
            embed.description = "Found an archived version on the Wayback Machine."
            embed.add_field(name="Wayback Machine", value=result.wayback_url, inline=False)
        elif result.wayback_saved:
            embed.description = "Submitted to Wayback Machine for archiving."
            embed.add_field(
                name="Wayback Machine", 
                value=f"Archiving in progress. Check back shortly at:\nhttps://web.archive.org/web/{url}", 
                inline=False
            )
        elif result.wayback_error:
            embed.description = f"Wayback Machine: {result.wayback_error}"
        else:
            embed.description = "No Wayback Machine archive found."
        
        # archive.today fallback
        embed.add_field(
            name="Alternative Archive",
            value=f"Try [archive.today]({result.archive_today_search}) or [create new archive]({result.archive_today_save})",
            inline=False
        )
        
        await message.reply(embed=embed, mention_author=False)
    
    @commands.hybrid_command(name="archive", description="Get archived version of a URL")
    @app_commands.describe(url="The URL to archive")
    async def manual_archive(self, ctx: commands.Context, url: str):
        """Get archived version of a URL using Wayback Machine and archive.today."""
        if not url.startswith("http"):
            url = "https://" + url
        
        await ctx.defer()
        result = await self.bot.archive_service.get_archive(url)
        
        embed = discord.Embed(
            title="Archive Results",
            color=discord.Color.blue()
        )
        
        # Wayback Machine result
        if result.wayback_url:
            embed.description = "Found an archived version on the Wayback Machine."
            embed.add_field(name="Wayback Machine", value=result.wayback_url, inline=False)
        elif result.wayback_saved:
            embed.description = "Submitted to Wayback Machine for archiving."
            embed.add_field(
                name="Wayback Machine", 
                value=f"Archiving in progress. Check back shortly at:\nhttps://web.archive.org/web/{url}", 
                inline=False
            )
        elif result.wayback_error:
            embed.description = f"Wayback Machine: {result.wayback_error}"
        else:
            embed.description = "No Wayback Machine archive found."
        
        # archive.today fallback
        embed.add_field(
            name="Alternative Archive",
            value=f"Try [archive.today]({result.archive_today_search}) or [create new archive]({result.archive_today_save})",
            inline=False
        )
        
        await ctx.send(embed=embed)


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN environment variable not set.")
        print("Please copy .env.example to .env and add your bot token.")
        return
    
    bot = ArchiveBot()
    bot.run(token)


if __name__ == "__main__":
    main()
