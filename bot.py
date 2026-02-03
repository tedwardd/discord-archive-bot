import os
import re
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from urllib.parse import urlparse

from database import init_db, add_paywall_site, remove_paywall_site, get_paywall_sites, is_paywall_site
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
        super().__init__(command_prefix=prefix, intents=intents)
        
        self.archive_service = ArchiveService()
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        await init_db()
        await self.add_cog(PaywallCog(self))
        await self.add_cog(ArchiveCog(self))
        # Sync slash commands
        await self.tree.sync()
    
    async def close(self):
        """Cleanup when bot shuts down."""
        await self.archive_service.close()
        await super().close()


class PaywallCog(commands.Cog, name="Paywall Management"):
    """Commands for managing the paywall sites list."""
    
    def __init__(self, bot: ArchiveBot):
        self.bot = bot
    
    @commands.hybrid_command(name="addsite", description="Add a domain to the paywall sites list")
    @app_commands.describe(domain="The domain to add (e.g., nytimes.com)")
    @commands.has_permissions(manage_messages=True)
    async def add_site(self, ctx: commands.Context, domain: str):
        """Add a domain to the paywall sites list."""
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
        
        added = await add_paywall_site(domain, str(ctx.author))
        if added:
            await ctx.send(f"Added `{domain}` to the paywall sites list.")
        else:
            await ctx.send(f"`{domain}` is already in the paywall sites list.")
    
    @commands.hybrid_command(name="removesite", description="Remove a domain from the paywall sites list")
    @app_commands.describe(domain="The domain to remove")
    @commands.has_permissions(manage_messages=True)
    async def remove_site(self, ctx: commands.Context, domain: str):
        """Remove a domain from the paywall sites list."""
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        
        removed = await remove_paywall_site(domain)
        if removed:
            await ctx.send(f"Removed `{domain}` from the paywall sites list.")
        else:
            await ctx.send(f"`{domain}` was not in the paywall sites list.")
    
    @commands.hybrid_command(name="listsites", description="List all paywall sites being monitored")
    async def list_sites(self, ctx: commands.Context):
        """List all domains in the paywall sites list."""
        sites = await get_paywall_sites()
        
        if not sites:
            await ctx.send("No paywall sites are currently being monitored.")
            return
        
        # Format the list nicely
        site_list = "\n".join(f"• `{site}`" for site in sites)
        
        embed = discord.Embed(
            title="Monitored Paywall Sites",
            description=site_list,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total: {len(sites)} sites")
        
        await ctx.send(embed=embed)


class ArchiveCog(commands.Cog, name="Archive"):
    """Commands and listeners for archive functionality."""
    
    def __init__(self, bot: ArchiveBot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages containing URLs to paywall sites."""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Find all URLs in the message
        urls = URL_PATTERN.findall(message.content)
        
        if not urls:
            return
        
        paywall_sites = await get_paywall_sites()
        if not paywall_sites:
            return
        
        for url in urls:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                
                # Remove www. prefix for matching
                if domain.startswith("www."):
                    domain = domain[4:]
                
                # Check if this domain matches any paywall site
                is_paywall = any(
                    paywall_domain in domain or domain in paywall_domain
                    for paywall_domain in paywall_sites
                )
                
                if is_paywall:
                    await self._handle_paywall_url(message, url)
                    
            except Exception as e:
                print(f"Error processing URL {url}: {e}")
    
    async def _handle_paywall_url(self, message: discord.Message, url: str):
        """Handle a URL from a paywall site."""
        # Show typing indicator while we check
        async with message.channel.typing():
            result = await self.bot.archive_service.check_and_archive(url)
        
        if result.found and result.archive_url:
            embed = discord.Embed(
                title="Archived Version Found",
                description="Here's an archived version of that article:",
                color=discord.Color.green()
            )
            embed.add_field(name="Archive Link", value=result.archive_url, inline=False)
            await message.reply(embed=embed, mention_author=False)
            
        elif result.error:
            embed = discord.Embed(
                title="Archive Check Failed",
                description=result.error,
                color=discord.Color.red()
            )
            if result.archive_url:
                embed.add_field(name="Archive Manually", value=result.archive_url, inline=False)
            await message.reply(embed=embed, mention_author=False)
            
        else:
            # No archive found - provide manual link
            embed = discord.Embed(
                title="No Archive Found",
                description=(
                    "This page has not been archived yet.\n\n"
                    "Click the link below to archive it manually (may require CAPTCHA)."
                ),
                color=discord.Color.orange()
            )
            embed.add_field(name="Archive This Page", value=result.archive_url, inline=False)
            await message.reply(embed=embed, mention_author=False)
    
    @commands.hybrid_command(name="archive", description="Check for an archived version of a URL")
    @app_commands.describe(url="The URL to check")
    async def manual_archive(self, ctx: commands.Context, url: str):
        """Check if a URL is archived and provide a link if not."""
        if not url.startswith("http"):
            url = "https://" + url
        
        await ctx.defer()
        result = await self.bot.archive_service.check_and_archive(url)
        
        if result.found and result.archive_url:
            embed = discord.Embed(
                title="Archived Version Found",
                description="Here's an archived version:",
                color=discord.Color.green()
            )
            embed.add_field(name="Archive Link", value=result.archive_url, inline=False)
            await ctx.send(embed=embed)
            
        elif result.error:
            embed = discord.Embed(
                title="Archive Check Failed",
                description=result.error,
                color=discord.Color.red()
            )
            if result.archive_url:
                embed.add_field(name="Archive Manually", value=result.archive_url, inline=False)
            await ctx.send(embed=embed)
            
        else:
            embed = discord.Embed(
                title="No Archive Found",
                description=(
                    "This page has not been archived yet.\n\n"
                    "Click the link below to archive it manually (may require CAPTCHA)."
                ),
                color=discord.Color.orange()
            )
            embed.add_field(name="Archive This Page", value=result.archive_url, inline=False)
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
